"""Remove the synthetic tenants that test runs leave behind.

``sites_e2e_fixture cleanup`` only removes a fixture nobody used: it refuses as
soon as the tenant holds Sites data, which is precisely what the test it
prepares goes on to create. So every local run leaves an account, an
organization and a tree of tenant rows behind, and after a few weeks the
account list is mostly rubble.

Every tenant row points at its organization with ``on_delete=PROTECT``
(``TenantScopedModel``), so deleting an organization fails loudly instead of
quietly taking a subtree with it. That default is right and this command does
not weaken it: it walks the refusals Django raises, removes what stands in the
way and tries again. It therefore needs no list of modules, cannot fall out of
date when a module adds a table, and Core stays unaware of Shared.

The guard is the address. Only the reserved test domains may be purged (RFC
2606 example.* and RFC 6761 .test/.invalid), and an organization whose members
include one real address is left alone — a real account must never disappear as
a side effect of tidying up after a test. Dry run unless ``--apply`` is given.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from django.apps import apps
from django.contrib.admin.utils import NestedObjects
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import ForeignKey, Model, ProtectedError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import Membership, Organization

RESERVED_DOMAIN_SUFFIXES = (".test", ".invalid", ".example")
RESERVED_DOMAINS = frozenset({"example.com", "example.net", "example.org"})

# A protected row is protected by another; the chain is short in practice
# (organization -> site -> page -> block). The limit only stops a cycle from
# recursing forever.
MAX_PROTECTED_DEPTH = 24


def is_reserved_email(email: str) -> bool:
    domain = email.rpartition("@")[2].strip().lower()
    if not domain:
        return False
    return domain in RESERVED_DOMAINS or domain.endswith(RESERVED_DOMAIN_SUFFIXES)


def organization_scoped_models() -> list[tuple[type[Model], str]]:
    """Every model that names an organization, with the field that names it.

    Discovered from the model metadata rather than declared, so a module added
    later is covered without touching this command. Where a model has more than
    one such field the first one wins — that is the tenant it belongs to.
    """
    scoped: list[tuple[type[Model], str]] = []
    for model in apps.get_models():
        if model is Organization:
            continue
        for field in model._meta.get_fields():
            if isinstance(field, ForeignKey) and field.related_model is Organization:
                scoped.append((model, field.name))
                break
    return scoped


def _purge_context(organization_id: uuid.UUID) -> TenantContext:
    """A context that exists only so tenant-scoped managers can answer.

    Deletion reads through ``TenantScopedManager``, which refuses without a
    context. Nothing here grants a permission: the command carries no actor and
    checks no permission, because it is an operator tool, not a request.
    """
    return TenantContext(
        organization_id=organization_id,
        membership_id=uuid.uuid7(),
        actor_id=uuid.uuid7(),
        role_key="purge",
        permissions=frozenset(),
    )


def _force_delete(instance: Model, *, depth: int = 0) -> None:
    if instance.pk is None:
        return
    if depth > MAX_PROTECTED_DEPTH:
        raise CommandError(
            f"Łańcuch zależności {instance._meta.label} jest zbyt głęboki — "
            "przerywam, żeby nie usuwać w pętli."
        )
    try:
        instance.delete()
    except ProtectedError as error:
        for protector in list(error.protected_objects):
            _force_delete(protector, depth=depth + 1)
        instance.delete()


def organization_row_counts(organization: Organization) -> Counter[str]:
    counts: Counter[str] = Counter()
    with transaction.atomic():
        set_local_organization_id(organization.id)
        with activate_tenant_context(_purge_context(organization.id)):
            for model, field_name in organization_scoped_models():
                found = model._base_manager.filter(
                    **{f"{field_name}_id": organization.id}
                ).count()
                if found:
                    counts[model._meta.label] = found
    return counts


def user_row_counts(user: User) -> Counter[str]:
    collector = NestedObjects(using="default")
    collector.collect([user])
    counts: Counter[str] = Counter()
    for model, instances in collector.data.items():
        counts[model._meta.label] += len(instances)
    for protected in collector.protected:
        counts[protected._meta.label] += 1
    return counts


def purge_organization(organization: Organization) -> None:
    with transaction.atomic():
        set_local_organization_id(organization.id)
        with activate_tenant_context(_purge_context(organization.id)):
            _force_delete(organization)


def purge_user(user: User) -> None:
    with transaction.atomic():
        _force_delete(user)


def _organizations_of(user: User) -> list[Organization]:
    # Membership is not tenant-scoped, so this reads across organizations on
    # purpose: the point is to find every tenant this account belongs to.
    organization_ids = Membership.objects.filter(user=user).values_list(
        "organization_id", flat=True
    )
    return list(Organization.objects.filter(id__in=list(organization_ids)))


def _real_members(organization: Organization) -> list[str]:
    emails = Membership.objects.filter(organization=organization).values_list(
        "user__email", flat=True
    )
    return sorted(email for email in emails if not is_reserved_email(email))


class Command(BaseCommand):
    help = (
        "Usuwa syntetyczne konta testowe i ich organizacje. Domyślnie tylko "
        "wypisuje plan; usuwa dopiero z --apply."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--email",
            action="append",
            default=[],
            help="Konto do usunięcia; można podać wielokrotnie.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Wszystkie konta na zastrzeżonych domenach testowych.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Wykonaj usunięcie zamiast wypisania planu.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        emails = [str(email).strip().lower() for email in options["email"]]
        if not emails and not options["all"]:
            raise CommandError("Podaj --email albo --all.")

        users = self._resolve_users(emails=emails, sweep=bool(options["all"]))
        if not users:
            self.stdout.write("Nie ma czego usuwać.")
            return

        organizations: dict[uuid.UUID, Organization] = {}
        skipped: list[tuple[User, str]] = []
        for user in users:
            reasons = []
            for organization in _organizations_of(user):
                real = _real_members(organization)
                if real:
                    reasons.append(
                        f"organizacja {organization.slug} ma prawdziwych "
                        f"członków: {', '.join(real)}"
                    )
                else:
                    organizations[organization.id] = organization
            if reasons:
                skipped.append((user, "; ".join(reasons)))

        skipped_users = {user.pk for user, _ in skipped}
        # An organization kept for one account must not be emptied for another.
        for user, _reason in skipped:
            for organization in _organizations_of(user):
                organizations.pop(organization.id, None)
        doomed = [user for user in users if user.pk not in skipped_users]

        self._report(doomed, list(organizations.values()), skipped)
        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING("Plan bez zmian. Uruchom ponownie z --apply.")
            )
            return

        for organization in organizations.values():
            purge_organization(organization)
            self.stdout.write(f"usunięto organizację {organization.slug}")
        for user in doomed:
            purge_user(user)
            self.stdout.write(f"usunięto konto {user.email}")
        self.stdout.write(
            self.style.SUCCESS(
                f"Usunięto {len(doomed)} kont i {len(organizations)} organizacji."
            )
        )

    def _resolve_users(self, *, emails: list[str], sweep: bool) -> list[User]:
        selected: dict[uuid.UUID, User] = {}
        for email in emails:
            user = User.objects.filter(email=email).first()
            if user is None:
                raise CommandError(f"Nie ma konta {email}.")
            if not is_reserved_email(user.email):
                raise CommandError(
                    f"Konto {email} nie jest na zastrzeżonej domenie testowej — "
                    "odmawiam usunięcia."
                )
            selected[user.pk] = user
        if sweep:
            for user in User.objects.order_by("date_joined"):
                if is_reserved_email(user.email):
                    selected[user.pk] = user
        return list(selected.values())

    def _report(
        self,
        users: list[User],
        organizations: list[Organization],
        skipped: list[tuple[User, str]],
    ) -> None:
        for organization in organizations:
            counts = organization_row_counts(organization)
            self.stdout.write(f"organizacja {organization.slug} ({organization.name}):")
            for label, found in sorted(counts.items()):
                self.stdout.write(f"    {label}: {found}")
        for user in users:
            counts = user_row_counts(user)
            summary = ", ".join(
                f"{label}: {found}" for label, found in sorted(counts.items())
            )
            self.stdout.write(f"konto {user.email}: {summary}")
        for user, reason in skipped:
            self.stdout.write(self.style.WARNING(f"pomijam {user.email}: {reason}"))
