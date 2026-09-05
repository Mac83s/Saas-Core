"""Provisions the deployment's own publisher workspace.

An operator action, not a signup: the workspace that carries the product's
marketing pages and blog is never created by somebody filling in a form, and it
is never billed. Running this twice is safe — it reports what already existed
rather than making a second one.

It lives in ``shared.billing`` rather than ``core.organizations`` because the
half that needs a home is the entitlement grant: creating the workspace itself
is a Core service (``ensure_platform_workspace``), but granting it features goes
through the billing override path, and Core must not import Shared.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from saas_core.modules.core.identity.mfa import has_confirmed_mfa
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    MembershipStatus,
    Role,
)
from saas_core.modules.core.organizations.platform_workspace import (
    PlatformWorkspaceConflict,
    ensure_platform_workspace,
)
from saas_core.modules.shared.billing.overrides import (
    OverrideTargetConflict,
    create_entitlement_override,
)

#: What the platform's own site needs to exist at all. Granted through the same
#: audited override path an operator would use for a customer, so the workspace
#: has no privileged route around the entitlement checks (W9.6.1).
INTERNAL_FEATURES = ("sites.enabled", "storage.enabled")


class Command(BaseCommand):
    help = "Tworzy workspace platformy dla tego deploymentu i nadaje mu wewnętrzne entitlementy."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--operator",
            required=True,
            help="E-mail operatora, który staje się właścicielem workspace'u.",
        )
        parser.add_argument("--name", default=None, help="Nazwa workspace'u.")

    def handle(self, *args: Any, **options: Any) -> None:
        email = User.objects.normalize_email(str(options["operator"]))
        operator = User.objects.filter(email=email).first()
        if operator is None or not operator.is_active:
            raise CommandError(f"Operator {email} nie istnieje albo jest nieaktywny.")
        if not operator.is_staff:
            # The same bar the entitlement override path sets: only an operator
            # grants internal entitlements, and this command grants several.
            raise CommandError(f"Operator {email} nie ma uprawnień operatorskich.")
        if not has_confirmed_mfa(operator):
            # Membership here is unreachable without MFA anyway; failing now
            # spares an operator a workspace they cannot enter.
            raise CommandError(
                f"Operator {email} musi mieć potwierdzone MFA przed wejściem do workspace'u."
            )

        try:
            organization, created = ensure_platform_workspace(name=options["name"])
        except PlatformWorkspaceConflict as error:
            raise CommandError(str(error.detail)) from error

        with transaction.atomic():
            # ADR-041: membership carries a policy, so the operator's own
            # membership in the workspace is written from inside it.
            set_local_organization_id(organization.id)
            owner_role = Role.objects.select_for_update().get(key="owner", organization=None)
            membership, membership_created = Membership.objects.get_or_create(
                organization=organization,
                user=operator,
                defaults={"role": owner_role, "status": MembershipStatus.ACTIVE},
            )
            if not membership_created and membership.status != MembershipStatus.ACTIVE:
                membership.status = MembershipStatus.ACTIVE
                membership.save(update_fields=["status", "updated_at"])

        enabled = self._grant_internal_features(
            organization_id=organization.id,
            membership_id=membership.id,
            operator=operator,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Workspace {organization.slug} "
                f"({'utworzony' if created else 'już istniał'}), "
                f"entitlementy aktywne: {', '.join(enabled) if enabled else 'brak'}."
            )
        )

    def _grant_internal_features(
        self, *, organization_id: Any, membership_id: Any, operator: User
    ) -> list[str]:
        context = TenantContext(
            organization_id=organization_id,
            membership_id=membership_id,
            actor_id=operator.id,
            role_key="owner",
            permissions=frozenset({"organization.billing.manage"}),
        )
        # Reports what is enabled afterwards, not what this run happened to
        # write: `create_entitlement_override` returns the existing grant on an
        # idempotency-key match, and claiming to have granted it again would be
        # a false report.
        enabled: list[str] = []
        for feature_key in INTERNAL_FEATURES:
            with transaction.atomic(), activate_tenant_context(context):
                set_local_organization_id(organization_id)
                try:
                    create_entitlement_override(
                        actor=operator,
                        reason="Workspace platformy — entitlement wewnętrzny (W9.6.1).",
                        idempotency_key=f"platform-workspace:{feature_key}",
                        feature_key=feature_key,
                        enabled=True,
                    )
                except OverrideTargetConflict:
                    # Already granted by an earlier run; the command is meant to
                    # be safe to repeat.
                    continue
            enabled.append(feature_key)
        return enabled
