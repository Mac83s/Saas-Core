"""Whether a company requires two-factor sign-in of its people (owner answer
35a, 2026-10-03; ADR-078).

"nie wymagaj" by default; MedPlano's new companies start at "role
zarządzające" — its profile's `settingsDefaults`, copied at a company's
creation and never read live, so existing companies keep "nie wymagaj" until
they change it (coordinator decision on 35a, 03.10). Who counts as managing: a role that changes the
company's settings or decides who gets in — settings, members, or members in a
limited way; an account taken over in any of these hurts the company alike.
Billing is left out on purpose: every billing change asks for a code anyway
(31b).

The gate that refuses a person without 2FA on entering the company is the
identity's (development-1b, `organization_mfa_required`); this module only
answers whether the requirement covers a membership. Switching the
requirement on signs nobody out: it blocks the next request. So the change
says first how many people it would shut out, and refuses to shut out the
person making it (development-1b, 03.10).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from django.core.cache import cache

from .command_registry import Effect
from .models import Membership, MembershipStatus
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


def _covered(requirement: str, permissions: Iterable[str]) -> bool:
    if requirement == "all":
        return True
    return requirement == "managers" and bool(MANAGING_PERMISSIONS & set(permissions))


def _shut_out(requirement: str, before: str = "none") -> list[Membership]:
    """The company's active people without 2FA whom `requirement` covers and
    `before` did not: those who lose access with the change."""
    from saas_core.modules.core.identity.models import UserMfaMethod  # noqa: PLC0415

    from .context import require_tenant_context  # noqa: PLC0415

    covered = [
        member
        for member in Membership.objects.select_related("role").filter(
            organization_id=require_tenant_context().organization_id,
            status=MembershipStatus.ACTIVE,
        )
        if _covered(requirement, member.role.permissions or ())
        and not _covered(before, member.role.permissions or ())
    ]
    with_mfa = set(
        UserMfaMethod.objects.filter(
            user_id__in=[member.user_id for member in covered], confirmed_at__isnull=False
        ).values_list("user_id", flat=True)
    )
    return [member for member in covered if member.user_id not in with_mfa]


def _refuse_self_lockout(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, tuple[str, str]]:
    """Whoever switches the requirement on without 2FA would lose the very
    page that switches it off."""
    from .context import require_tenant_context  # noqa: PLC0415

    me = require_tenant_context().membership_id
    if me is None or all(
        member.id != me for member in _shut_out(after["mfa_required"], before["mfa_required"])
    ):
        return {}
    return {
        "mfa_required": (
            "Najpierw włącz weryfikację dwuetapową na swoim koncie — bez niej ta zmiana "
            "zamknęłaby Ci dostęp do firmy.",
            "mfa_required_self",
        )
    }


def _lockout_effects(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[Effect, ...]:
    count = len(_shut_out(after["mfa_required"], before["mfa_required"]))
    if not count:
        return ()
    if count == 1:
        pl = "1 osoba w firmie straci dostęp, dopóki nie włączy 2FA."
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        pl = f"{count} osoby w firmie stracą dostęp, dopóki nie włączą 2FA."
    else:
        pl = f"{count} osób w firmie straci dostęp, dopóki nie włączy 2FA."
    en = (
        "1 person in the company loses access until they turn on 2FA."
        if count == 1
        else f"{count} people in the company lose access until they turn on 2FA."
    )
    return (
        Effect(
            kind="access_blocked",
            resource="organization.membership",
            resource_id="",
            summary={"pl": pl, "en": en},
        ),
    )


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
    check=_refuse_self_lockout,
    effects=_lockout_effects,
    on_changed=_forget,
    commands=("organization.settings_security.read@1", "organization.settings_security.update@1"),
    settings=(
        SettingSpec(
            key=MFA_REQUIRED,
            type="enum",
            default="none",
            scopes=("organization",),
            # A product's "managers" is where a new company starts; one older
            # than it keeps "none", so nobody is shut out mid-work.
            inheritance="copy_at_creation",
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
    return _covered(mfa_requirement(membership.organization_id), membership.role.permissions or ())


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
