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
    Organization,
)
from saas_core.modules.core.organizations.platform_workspace import (
    PlatformWorkspaceConflict,
    ensure_platform_workspace,
)
from saas_core.modules.core.organizations.role_catalog import system_roles
from saas_core.modules.shared.billing.models import EntitlementGrant, GrantSource
from saas_core.modules.shared.billing.overrides import (
    OverrideTargetConflict,
    create_entitlement_override,
)
from saas_core.modules.shared.billing.snapshots import refresh_internal_snapshot

#: What the platform's own site needs to exist and to answer on the product's
#: domain (ADR-077). Granted through the same audited override path an operator
#: would use for a customer, so the workspace has no privileged route around
#: the entitlement checks (W9.6.1).
INTERNAL_FEATURES = ("sites.enabled", "storage.enabled", "custom_domain.enabled")
#: One site: `create_site` consumes `sites.max`, and a workspace without the
#: quota is refused, not unlimited. Pages have no limit where no plan names one.
INTERNAL_QUOTAS = {"sites.max": 1}
#: `storage.bytes` when the operator names no other size: every upload reserves
#: against it. The deployment's own disk is the real bound; this keeps a
#: runaway import from filling it.
DEFAULT_STORAGE_GIB = 20
GIB = 1024**3


class Command(BaseCommand):
    help = "Tworzy workspace platformy dla tego deploymentu i nadaje mu wewnętrzne entitlementy."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--operator",
            required=True,
            help="E-mail operatora, który staje się właścicielem workspace'u.",
        )
        parser.add_argument("--name", default=None, help="Nazwa workspace'u.")
        parser.add_argument(
            "--storage-gib",
            type=int,
            default=DEFAULT_STORAGE_GIB,
            help="Limit plików strony w GiB, nadawany przy pierwszym uruchomieniu "
            f"(domyślnie {DEFAULT_STORAGE_GIB}). Limit już nadany zmienia operator "
            "przez override, nie ta komenda.",
        )

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
            owner_role = (
                system_roles(organization.organization_type).select_for_update().get(key="owner")
            )
            membership, membership_created = Membership.objects.get_or_create(
                organization=organization,
                user=operator,
                defaults={"role": owner_role, "status": MembershipStatus.ACTIVE},
            )
            if not membership_created and membership.status != MembershipStatus.ACTIVE:
                membership.status = MembershipStatus.ACTIVE
                membership.save(update_fields=["status", "updated_at"])

        if options["storage_gib"] < 1:
            raise CommandError("--storage-gib musi być dodatnią liczbą.")
        features, quotas = self._grant_internal_entitlements(
            organization_id=organization.id,
            membership_id=membership.id,
            operator=operator,
            quotas={**INTERNAL_QUOTAS, "storage.bytes": options["storage_gib"] * GIB},
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Workspace {organization.slug} "
                f"({'utworzony' if created else 'już istniał'}), "
                f"entitlementy aktywne: {', '.join(features) if features else 'brak'}; "
                f"limity: {', '.join(f'{key}={value}' for key, value in quotas.items())}."
            )
        )

    def _grant_internal_entitlements(
        self,
        *,
        organization_id: Any,
        membership_id: Any,
        operator: User,
        quotas: dict[str, int],
    ) -> tuple[list[str], dict[str, int]]:
        """Grants what is missing and reports what is in force afterwards —
        not what this run happened to write. A target that already has an
        active grant is left alone, whoever granted it and whatever its value:
        the command is safe to repeat by any operator, and a limit an operator
        changed since stays changed."""
        context = TenantContext(
            organization_id=organization_id,
            membership_id=membership_id,
            actor_id=operator.id,
            role_key="owner",
            permissions=frozenset({"organization.billing.manage"}),
        )
        targets: list[dict[str, Any]] = [
            {"feature_key": key, "enabled": True} for key in INTERNAL_FEATURES
        ] + [{"quota_key": key, "limit_value": value} for key, value in quotas.items()]
        for target in targets:
            key = target.get("feature_key") or target["quota_key"]
            with transaction.atomic(), activate_tenant_context(context):
                set_local_organization_id(organization_id)
                # A key per attempt: the one a revoked grant used would hand
                # that revoked grant back instead of granting again.
                earlier = EntitlementGrant.all_objects.filter(
                    organization_id=organization_id,
                    source=GrantSource.OVERRIDE,
                    idempotency_key__startswith=f"platform-workspace:{key}",
                ).count()
                try:
                    create_entitlement_override(
                        actor=operator,
                        reason="Workspace platformy — entitlement wewnętrzny (W9.6.1, ADR-077).",
                        idempotency_key=f"platform-workspace:{key}"
                        + (f":{earlier}" if earlier else ""),
                        **target,
                    )
                except OverrideTargetConflict:
                    # Already in force from an earlier run or an operator's
                    # own override.
                    continue
        with transaction.atomic():
            set_local_organization_id(organization_id)
            organization = Organization.objects.select_for_update().get(pk=organization_id)
            snapshot = refresh_internal_snapshot(organization)
        return (
            sorted(key for key, on in snapshot.features.items() if on),
            dict(sorted(snapshot.quotas.items())),
        )
