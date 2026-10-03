"""Who manages the company's billing (owner answer 34a, 2026-10-03; ADR-078).

By default only the owner. The owner may let the roles that hold the billing
permission (`organization.billing.manage`) manage it too. Every billing
change still needs a fresh code from the authenticator app (31b); turning the
switch is itself a billing change: the owner's, with that code.
"""

from __future__ import annotations

from uuid import UUID

from saas_core.modules.core.organizations.api import (
    SettingArea,
    SettingGroup,
    SettingSpec,
    setting,
)
from saas_core.modules.core.organizations.authorization import (
    OrganizationPermissionDenied,
    authorize,
)
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.permissions import BILLING_MANAGE

DELEGATED = "billing.access.delegated"

BILLING_AREA = SettingArea(
    key="billing",
    title={"pl": "Plan i płatności", "en": "Plan & billing"},
    description={
        "pl": "Plan, płatności, dane do faktury i kto nimi zarządza.",
        "en": "The plan, payments, invoice details and who manages them.",
    },
    order=70,
    page="/panel/settings/billing",
)

ACCESS = SettingGroup(
    key="billing.access",
    module="shared.billing",
    title={"pl": "Kto zarządza rozliczeniami", "en": "Who manages billing"},
    description={
        "pl": "Domyślnie plan, płatności i dane do faktury zmienia tylko właściciel. Każda "
        "zmiana rozliczeń wymaga kodu z aplikacji uwierzytelniającej.",
        "en": "By default only the owner changes the plan, payments and invoice details. "
        "Every billing change needs a code from the authenticator app.",
    },
    permission=BILLING_MANAGE,
    owner_only=True,
    step_up_reason="billing",
    area="billing",
    settings=(
        SettingSpec(
            key=DELEGATED,
            type="bool",
            default=False,
            scopes=("organization",),
            product_default=False,
            label={
                "pl": "Rozliczeniami zarządzają też role z uprawnieniem Rozliczenia",
                "en": "Roles with the Billing permission manage billing too",
            },
            help={
                "pl": "Np. księgowa z rolą z uprawnieniem Rozliczenia. Każda jej zmiana też "
                "wymaga kodu 2FA.",
                "en": "E.g. an accountant whose role has the Billing permission. Each of her "
                "changes needs a 2FA code too.",
            },
            model_description="Whether roles holding organization.billing.manage may change "
            "the plan, payments and invoice details, not only the owner. Only the owner "
            "turns it, with a code from the authenticator app.",
        ),
    ),
)


def billing_manager() -> TenantContext:
    """The owner — or, when the owner allowed it, a role with the billing
    permission. The 403 comes before any request for a code."""
    context = authorize(BILLING_MANAGE)
    if context.role_key != "owner" and not setting(DELEGATED):
        raise OrganizationPermissionDenied
    return context


def may_manage_billing(context: TenantContext) -> bool:
    return context.has_permission(BILLING_MANAGE) and (
        context.role_key == "owner" or bool(setting(DELEGATED))
    )


def billing_delegated(organization_id: UUID) -> bool:
    """For per-company work with that company's tenant set (warnings)."""
    return bool(setting(DELEGATED, organization_id=organization_id))
