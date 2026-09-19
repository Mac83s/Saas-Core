from __future__ import annotations

import os
import re
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from saas_core.modules.core.identity.models import AccountAuditEvent, User, UserStatus
from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
    OrganizationStatus,
)
from saas_core.modules.core.organizations.pre_tenant import PRE_TENANT_DB
from saas_core.modules.core.organizations.role_catalog import system_role
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)
from saas_core.modules.shared.sites.models import Site

FIXTURE_PREFIX = "w6-e2e-"
EMAIL_PATTERN = re.compile(r"^w6-e2e-[a-z0-9-]+@example\.test$")


class Command(BaseCommand):
    help = "Create or remove an isolated synthetic tenant for the W6 Playwright test."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("action", choices=("prepare", "cleanup"))
        parser.add_argument("--email", required=True)
        parser.add_argument("--slug", required=True)

    def handle(self, *args: Any, **options: Any) -> str:
        email = str(options["email"]).strip().lower()
        slug = str(options["slug"]).strip().lower()
        self._validate_identifiers(email=email, slug=slug)

        if options["action"] == "cleanup":
            removed = cleanup_fixture(email=email, slug=slug)
            return f"W6 E2E fixture removed: {removed}"

        password = os.environ.get("SITES_E2E_PASSWORD", "")
        if len(password) < 16:
            raise CommandError("SITES_E2E_PASSWORD must contain at least 16 characters.")
        with transaction.atomic():
            # ADR-041: the registry carries row-level security, and this asks
            # whether a slug is taken across every tenant.
            if (
                Organization.objects.using(PRE_TENANT_DB).filter(slug=slug).exists()
                or User.objects.filter(email=email).exists()
            ):
                raise CommandError("The requested W6 E2E fixture already exists.")
            user = User.objects.create_user(email=email, password=password)
            user.status = UserStatus.ACTIVE
            user.save(update_fields=["status", "is_active"])
            organization = Organization(
                name=f"W6 E2E {slug.removeprefix(FIXTURE_PREFIX)}",
                slug=slug,
                status=OrganizationStatus.ACTIVE,
            )
            # The identifier exists before the row does, so everything below is
            # written under the policy that guards it.
            set_local_organization_id(organization.id)
            organization.save()
            Membership.objects.create(
                organization=organization,
                user=user,
                role=system_role(organization.organization_type, "admin"),
            )
            # billing_entitlementsnapshot forces row-level security (ADR-039),
            # and the app role has no way in without the tenant being set. The
            # insert is refused rather than silently dropped, which is the
            # right direction — and it was set above.
            EntitlementSnapshot.all_objects.create(
                organization=organization,
                subscription_state=SubscriptionState.ACTIVE,
                access_mode=AccessMode.FULL,
                features={
                    "sites.enabled": True,
                    "storage.enabled": True,
                    "custom_domain.enabled": True,
                },
                quotas={"sites.max": 3, "storage.bytes": 10_000_000},
                sources={
                    "sites.enabled": {"kind": "e2e"},
                    "sites.max": {"kind": "e2e"},
                    "storage.enabled": {"kind": "e2e"},
                    "custom_domain.enabled": {"kind": "e2e"},
                    "storage.bytes": {"kind": "e2e"},
                },
            )
        return f"W6 E2E fixture ready: {slug}"

    @staticmethod
    def _validate_identifiers(*, email: str, slug: str) -> None:
        if not slug.startswith(FIXTURE_PREFIX) or not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", slug
        ):
            raise CommandError(f"Slug must use the reserved {FIXTURE_PREFIX} prefix.")
        if EMAIL_PATTERN.fullmatch(email) is None:
            raise CommandError("Email must use the reserved W6 E2E example.test pattern.")


@transaction.atomic
def cleanup_fixture(*, email: str, slug: str) -> bool:
    # ADR-041: finding a tenant by slug is a question about the registry; the
    # identifier it answers with is what everything below runs inside.
    organization_id = (
        Organization.objects.using(PRE_TENANT_DB)
        .filter(slug=slug)
        .values_list("id", flat=True)
        .first()
    )
    user = User.objects.filter(email=email).first()
    if organization_id is not None:
        set_local_organization_id(organization_id)
        if Site.all_objects.filter(organization_id=organization_id).exists():
            raise CommandError(
                "Refusing to remove a W6 E2E fixture containing persisted Sites data."
            )
        OrganizationAuditEntry.objects.filter(organization_id=organization_id).delete()
        EntitlementSnapshot.all_objects.filter(organization_id=organization_id).delete()
        Membership.objects.filter(organization_id=organization_id).delete()
        Organization.objects.filter(pk=organization_id).delete()
    if (
        user is not None
        and not Membership.objects.using(PRE_TENANT_DB).filter(user=user).exists()
    ):
        AccountAuditEvent.objects.filter(subject_user=user).delete()
        AccountAuditEvent.objects.filter(actor_user=user).delete()
        user.delete()
    return organization_id is not None or user is not None
