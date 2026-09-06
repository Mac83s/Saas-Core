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

from django.contrib.admin.utils import NestedObjects
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError, transaction
from django.db.models import Model, ProtectedError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.erasure import (
    ErasureBlocked,
    erase_organization,
    row_counts,
)
from saas_core.modules.core.organizations.models import Membership, Organization
from saas_core.modules.core.organizations.pre_tenant import PRE_TENANT_DB

RESERVED_DOMAIN_SUFFIXES = (".test", ".invalid", ".example")
RESERVED_DOMAINS = frozenset({"example.com", "example.net", "example.org"})

# Removing an account walks a short chain (user -> audit event). The limit only
# stops a cycle from recursing forever; tenant rows, where the cycles actually
# are, are emptied in passes instead — see purge_organization.
MAX_PROTECTED_DEPTH = 24


def is_reserved_email(email: str) -> bool:
    domain = email.rpartition("@")[2].strip().lower()
    if not domain:
        return False
    return domain in RESERVED_DOMAINS or domain.endswith(RESERVED_DOMAIN_SUFFIXES)


#: Removing an account walks a short chain (user -> audit event). The limit only
#: stops a cycle from recursing forever; tenant rows are emptied by the erasure
#: service, which knows how to open the append-only guards (ADR-042).
MAX_PROTECTED_DEPTH = 24


def _first_line(error: Exception) -> str:
    text = str(error).strip()
    return text.splitlines()[0] if text else error.__class__.__name__


def _delete_row(instance: Model) -> None:
    """Delete one row even when its model refuses on ``delete()``.

    Mutation logs and versions raise on purpose: nothing in the application may
    erase what happened. The queryset does not run that guard; what the database
    enforces itself still stands.
    """
    try:
        instance.delete()
    except ValidationError:
        type(instance)._base_manager.filter(pk=instance.pk).delete()


def _force_delete(instance: Model, *, depth: int = 0) -> None:
    if instance.pk is None:
        return
    if depth > MAX_PROTECTED_DEPTH:
        raise CommandError(
            f"Łańcuch zależności {instance._meta.label} jest zbyt głęboki — "
            "przerywam, żeby nie usuwać w pętli."
        )
    try:
        _delete_row(instance)
    except ProtectedError as error:
        for protector in list(error.protected_objects):
            _force_delete(protector, depth=depth + 1)
        _delete_row(instance)


def organization_row_counts(organization: Organization) -> Counter[str]:
    """What the dry run reports, taken from the erasure service's own count."""
    return Counter(row_counts(organization.id))


def user_row_counts(user: User) -> Counter[str]:
    # ADR-041: an account's rows live in whichever organizations it belongs to,
    # and a dry run that under-reports because it stands outside all of them
    # would be worse than no dry run at all.
    collector = NestedObjects(using=PRE_TENANT_DB)
    collector.collect([user])
    counts: Counter[str] = Counter()
    for model, instances in collector.data.items():
        counts[model._meta.label] += len(instances)
    for protected in collector.protected:
        counts[protected._meta.label] += 1
    return counts


def purge_user(user: User) -> None:
    with transaction.atomic():
        _force_delete(user)


def _organizations_of(user: User) -> list[Organization]:
    # ADR-041: reads across organizations on purpose — the point is to find
    # every tenant this account belongs to, which is the same question the
    # switcher asks and cannot be asked from inside one of them.
    organization_ids = Membership.objects.using(PRE_TENANT_DB).filter(user=user).values_list(
        "organization_id", flat=True
    )
    return list(
        Organization.objects.using(PRE_TENANT_DB).filter(id__in=list(organization_ids))
    )


def _real_members(organization: Organization) -> list[str]:
    # The guard that keeps a real account from disappearing as a side effect of
    # tidying up. It runs before any tenant is chosen, on an organization the
    # operator may not belong to.
    emails = (
        Membership.objects.using(PRE_TENANT_DB)
        .filter(organization=organization)
        .values_list("user__email", flat=True)
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

        refused: list[tuple[Organization, str]] = []
        removed_organizations = 0
        for organization in organizations.values():
            try:
                erase_organization(
                    organization=organization,
                    requested_by=None,
                    reason="Sprzątanie tenantów testowych na zastrzeżonych domenach.",
                )
            except (ErasureBlocked, CommandError, DatabaseError, ValidationError) as error:
                # The database refused on its own — an append-only trigger, for
                # instance. That is not something an operator command may talk
                # its way past, so this tenant stays and the others continue.
                refused.append((organization, _first_line(error)))
                continue
            removed_organizations += 1
            self.stdout.write(f"usunięto organizację {organization.slug}")

        refused_ids = {organization.id for organization, _ in refused}
        removed_users = 0
        for user in doomed:
            if any(org.id in refused_ids for org in _organizations_of(user)):
                self.stdout.write(
                    self.style.WARNING(
                        f"pomijam {user.email}: jego organizacja została odmówiona"
                    )
                )
                continue
            purge_user(user)
            removed_users += 1
            self.stdout.write(f"usunięto konto {user.email}")

        for organization, reason in refused:
            self.stdout.write(
                self.style.ERROR(f"nie usunięto organizacji {organization.slug}: {reason}")
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Usunięto {removed_users} kont i {removed_organizations} organizacji."
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
