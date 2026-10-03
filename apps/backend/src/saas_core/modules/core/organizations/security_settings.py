"""Whether a company requires two-factor sign-in of its people (owner answer
35a, 2026-10-03; ADR-078).

"nie wymagaj" by default (MedPlano starts at "role zarządzające" through its
profile's `settingsDefaults`). Who counts as managing: a role that changes the
company's settings or decides who gets in — settings, members, or members in a
limited way; an account taken over in any of these hurts the company alike.
Billing is left out on purpose: every billing change asks for a code anyway
(31b).

The gate that refuses a person without 2FA on entering the company is the
identity's (development-1b, `organization_mfa_required`); this module only
answers whether the requirement covers a membership. Switching the
requirement on signs nobody out: it blocks the next request.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.cache import cache

from .models import Membership
from .permissions import MEMBERS_MANAGE, MEMBERS_MANAGE_LIMITED, SETTINGS_MANAGE
from .settings_registry import SettingGroup, SettingSpec
from .settings_service import setting

MFA_REQUIRED = "organization.security.mfa_required"
#: The permissions that make a role "managing" for the requirement.
MANAGING_PERMISSIONS = frozenset({SETTINGS_MANAGE, MEMBERS_MANAGE, MEMBERS_MANAGE_LIMITED})
#: Read on every request of a company: kept for a while, dropped on a change.
_CACHE_SECONDS = 300


def _cache_key(organization_id: Any) -> str:
    return f"organizations:settings:mfa_required:{organization_id}"


def _forget(before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    from .context import require_tenant_context  # noqa: PLC0415

    cache.delete(_cache_key(require_tenant_context().organization_id))


SECURITY = SettingGroup(
    key="organization.security",
    module="core.organizations",
    title={"pl": "Bezpieczeństwo", "en": "Security"},
    description={
        "pl": "Czy osoby w firmie muszą logować się z weryfikacją dwuetapową (2FA).",
        "en": "Whether the company's people must sign in with two-factor verification (2FA).",
    },
    permission=SETTINGS_MANAGE,
    area="security",
    on_changed=_forget,
    commands=("organization.settings_security.read@1", "organization.settings_security.update@1"),
    settings=(
        SettingSpec(
            key=MFA_REQUIRED,
            type="enum",
            default="none",
            scopes=("organization",),
            values=(
                ("none", {"pl": "Nie wymagaj", "en": "Do not require"}),
                ("managers", {"pl": "Role zarządzające", "en": "Managing roles"}),
                ("all", {"pl": "Wszyscy", "en": "Everyone"}),
            ),
            label={"pl": "Wymagaj weryfikacji dwuetapowej", "en": "Require two-factor sign-in"},
            help={
                "pl": "Role zarządzające to te, które zmieniają ustawienia firmy albo zarządzają "
                "zespołem. Osoba bez 2FA nie wejdzie do firmy, dopóki go nie włączy; "
                "zalogowanych nikt nie wylogowuje.",
                "en": "Managing roles are those that change the company's settings or manage "
                "its team. A person without 2FA cannot enter the company until they turn "
                "it on; nobody signed in is signed out.",
            },
            model_description="Who in the company must have two-factor sign-in: none, the "
            "managing roles (company settings or team management) or everyone. A person "
            "without it is refused entry to the company until they turn it on.",
        ),
    ),
)


def mfa_requirement(organization_id: Any) -> str:
    """`none`, `managers` or `all` for this company — with its tenant set, as
    the tenant middleware has it, so row-level security lets its row through."""
    key = _cache_key(organization_id)
    value = cache.get(key)
    if value is None:
        value = setting(MFA_REQUIRED, organization_id=organization_id)
        cache.set(key, value, _CACHE_SECONDS)
    return str(value)


def membership_requires_mfa(membership: Membership) -> bool:
    """Whether the company requires two-factor sign-in of this membership —
    not whether the person has it (the gate checks that)."""
    requirement = mfa_requirement(membership.organization_id)
    if requirement == "all":
        return True
    if requirement == "managers":
        return bool(MANAGING_PERMISSIONS & set(membership.role.permissions or ()))
    return False


def mfa_status(members: list[Membership]) -> frozenset[object] | None:
    """Which of these people sign in with 2FA — for who manages the team or the
    company's settings (35a); None for anyone else, who need not know which
    accounts are the weaker ones."""
    from saas_core.modules.core.identity.models import UserMfaMethod  # noqa: PLC0415

    from .context import current_tenant_context  # noqa: PLC0415

    context = current_tenant_context()
    if context is None or not any(
        context.has_permission(permission) for permission in MANAGING_PERMISSIONS
    ):
        return None
    return frozenset(
        UserMfaMethod.objects.filter(
            user_id__in=[member.user_id for member in members], confirmed_at__isnull=False
        ).values_list("user_id", flat=True)
    )
