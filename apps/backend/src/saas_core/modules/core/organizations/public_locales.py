"""The company's languages: one service changes them (ADR-071 pkt 4–7, ADR-078 pkt 5, 7, 9).

Every change — the settings page, the assistant's command, a site started in
a language the company did not have — goes through here: the plan's limit when
a language is added, the modules' vetoes when one is removed, a person's
decision for a removal, the languages' own version, the history
(`PublicLocalesChange`, also the request's receipt) and one audit row of the
settings group. Modules hook in from `AppConfig.ready`:

- `register_public_locales_limit` — how many languages beyond the first the
  plan allows (billing);
- `register_public_locales_guard` — a language a module does not let go, with
  its field code (sites: a site's source language);
- `register_public_locales_changed` — a reaction in the same transaction.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import APIException, ErrorDetail, ValidationError

from saas_core.modules.core.identity.models import User

from .audit import record_audit
from .authorization import authorize
from .canonical import canonical_json_hash
from .context import current_tenant_context
from .locales import LOCALE_NOT_IN_REGISTRY, assert_content_locale
from .models import (
    Organization,
    OrganizationAuditAction,
    PublicLocalesChange,
    PublicLocalesChangeOrigin,
    WorkspaceKind,
)
from .permissions import ORGANIZATION_READ, SETTINGS_MANAGE
from .person_gate import assert_person_required

#: The settings group: the audit row's target type and the history filter's key.
PUBLIC_LOCALES_GROUP = "organization.public_locales"
FIELD = "public_locales"
#: Removing a language takes its pages off the site: a person's decision.
REMOVAL_GATE = "Usunięcie języka firmy"

LOCALE_NOT_SUPPORTED = "locale_not_supported"
QUOTA_EXCEEDED = "quota_exceeded"
PLAN_ACCESS_DENIED = "plan_access_denied"

_DENIALS = {
    "read_only": "subskrypcja jest tylko do odczytu",
    "access_blocked": "dostęp do konta jest zablokowany",
    "snapshot_expired": "uprawnienia planu wygasły",
    "snapshot_missing": "firma nie ma jeszcze planu",
    "unknown_quota": "plan nie zna limitu języków",
}


@dataclass(frozen=True, slots=True)
class PublicLocalesLimit:
    #: Whether the plan lets the company add a language now.
    allowed: bool
    #: Languages beyond the first; None: no limit.
    additional_max: int | None = None
    #: Why not, when not allowed: the billing decision's reason.
    reason: str = ""


PublicLocalesGuard = Callable[[UUID, frozenset[str]], Mapping[str, str]]
PublicLocalesChanged = Callable[[Organization, tuple[str, ...], tuple[str, ...]], None]

_limits: list[Callable[[], PublicLocalesLimit]] = []
_guards: list[PublicLocalesGuard] = []
_changed: list[PublicLocalesChanged] = []


def register_public_locales_limit(limit: Callable[[], PublicLocalesLimit]) -> None:
    if limit not in _limits:
        _limits.append(limit)


def register_public_locales_guard(guard: PublicLocalesGuard) -> None:
    """`guard(organization_id, removed)` → {code: field code} of the languages
    it does not let go."""
    if guard not in _guards:
        _guards.append(guard)


def register_public_locales_changed(handler: PublicLocalesChanged) -> None:
    """`handler(organization, before, after)`, in the change's transaction."""
    if handler not in _changed:
        _changed.append(handler)


class SettingsVersionConflict(APIException):
    status_code = 409
    default_detail = "Języki firmy zmieniły się w międzyczasie. Odśwież je i spróbuj ponownie."
    default_code = "settings_version_conflict"


class SettingsIdempotencyConflict(APIException):
    status_code = 409
    default_detail = "Ten klucz idempotencji użyto już dla innej zmiany języków."
    default_code = "settings_idempotency_conflict"


@dataclass(frozen=True, slots=True)
class PublicLocales:
    locales: tuple[str, ...]
    version: int
    #: What a company of this product may choose from, in the registry's order.
    offered: tuple[str, ...]
    limit: PublicLocalesLimit
    #: The company's languages a module does not let go, with its field code.
    protected: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class PublicLocalesPlan:
    before: tuple[str, ...]
    after: tuple[str, ...]
    #: The version after the change; the same when nothing changes.
    version: int
    limit: PublicLocalesLimit
    #: The person-only decisions the change needs (a removal).
    person_gates: frozenset[str] = frozenset()
    #: The stored change; None for a preview and for a change of nothing.
    change: PublicLocalesChange | None = None

    @property
    def added(self) -> tuple[str, ...]:
        return tuple(code for code in self.after if code not in self.before)

    @property
    def removed(self) -> tuple[str, ...]:
        return tuple(code for code in self.before if code not in self.after)


def offered_locales() -> tuple[str, ...]:
    supported = set(settings.SITES_SUPPORTED_LOCALES)
    return tuple(code for code in settings.LOCALE_REGISTRY if code in supported)


def read_public_locales() -> PublicLocales:
    context = authorize(ORGANIZATION_READ)
    organization = Organization.objects.get(pk=context.organization_id)
    return PublicLocales(
        locales=tuple(organization.public_locales),
        version=organization.public_locales_version,
        offered=offered_locales(),
        limit=_limit(organization),
        protected=_protected(organization, frozenset(organization.public_locales)),
    )


@transaction.atomic
def change_public_locales(
    *,
    locales: Sequence[str],
    expected_version: int,
    idempotency_key: str,
    preview: bool = False,
) -> PublicLocalesPlan:
    """The company's languages become `locales`, in that order; the first is its
    customers' language. With `preview` nothing is saved: the answer is the
    change as it would be, with every problem the save would raise."""
    context = authorize(SETTINGS_MANAGE)
    key = "" if preview else _idempotency_key(idempotency_key)
    request_hash = canonical_json_hash({
        "public_locales": list(locales),
        "expected_version": expected_version,
    })
    organizations = Organization.objects.all()
    if not preview:
        organizations = organizations.select_for_update()
    organization = organizations.get(pk=context.organization_id)
    if key:
        done = PublicLocalesChange.objects.filter(
            organization_id=organization.id, idempotency_key=key
        ).first()
        if done is not None:
            if done.request_hash != request_hash:
                raise SettingsIdempotencyConflict
            return PublicLocalesPlan(
                before=tuple(done.before),
                after=tuple(done.after),
                version=done.version,
                limit=PublicLocalesLimit(allowed=True),
                change=done,
            )
    if organization.public_locales_version != expected_version:
        raise SettingsVersionConflict
    plan = _plan(organization, tuple(locales), field=FIELD)
    if plan.removed:
        if preview:
            plan = replace(plan, person_gates=frozenset({REMOVAL_GATE}))
        else:
            assert_person_required(context, REMOVAL_GATE)
    if preview or plan.after == plan.before:
        return plan
    change = _save(
        organization,
        plan,
        origin=PublicLocalesChangeOrigin.SETTINGS,
        actor_id=context.actor_id,
        key=key,
        request_hash=request_hash,
    )
    return replace(plan, change=change)


def include_site_source_locale(
    *, organization_id: Any, code: str, first: bool, idempotency_key: str
) -> None:
    """A site's source language is always one of the company's (ADR-071 pkt 6).

    `idempotency_key` is the site creation's own, unique in the company and at
    most 100 characters (a digest).

    Starting a site in a language of the profile that the company has not
    listed yet adds it — at the front when it is the company's first site, so
    the language the company chose to speak becomes its customers' language,
    at the end otherwise — through the same limit and history as the settings.
    Whoever may create a site may do this; it is not a change of settings.
    """
    organization = Organization.objects.select_for_update().get(pk=organization_id)
    if code in organization.public_locales:
        return
    if code not in settings.SITES_SUPPORTED_LOCALES:
        assert_content_locale(code, organization=organization, field="default_locale")
    before = tuple(organization.public_locales)
    plan = _plan(
        organization, (code, *before) if first else (*before, code), field="default_locale"
    )
    context = current_tenant_context()
    _save(
        organization,
        plan,
        origin=PublicLocalesChangeOrigin.SITE_SOURCE,
        actor_id=context.actor_id if context is not None else None,
        key=f"site-source:{idempotency_key}",
        request_hash=canonical_json_hash({"site_source": code, "key": idempotency_key}),
    )


def _plan(organization: Organization, after: tuple[str, ...], *, field: str) -> PublicLocalesPlan:
    before = tuple(organization.public_locales)
    offered = set(offered_locales())
    problems: list[ErrorDetail] = []
    if not after:
        problems.append(ErrorDetail("Firma musi mieć co najmniej jeden język.", code="required"))
    if len(set(after)) != len(after):
        problems.append(ErrorDetail("Każdy język może być na liście tylko raz.", code="duplicate"))
    for code in dict.fromkeys(after):
        if code not in settings.LOCALE_REGISTRY:
            problems.append(
                ErrorDetail(f"Języka {code} nie ma na platformie.", code=LOCALE_NOT_IN_REGISTRY)
            )
        elif code not in before and code not in offered:
            problems.append(
                ErrorDetail(f"Języka {code} nie ma w tym produkcie.", code=LOCALE_NOT_SUPPORTED)
            )
    removed = frozenset(code for code in before if code not in after)
    for code, problem in sorted(_protected(organization, removed).items()):
        problems.append(ErrorDetail(f"Języka {code} nie można usunąć.", code=problem))
    added = [code for code in after if code not in before]
    limit = _limit(organization) if added else PublicLocalesLimit(allowed=True)
    if added and not limit.allowed:
        why = _DENIALS.get(limit.reason, limit.reason)
        problems.append(
            ErrorDetail(f"Plan nie pozwala teraz dodać języka: {why}.", code=PLAN_ACCESS_DENIED)
        )
    elif added and limit.additional_max is not None and len(after) - 1 > limit.additional_max:
        problems.append(
            ErrorDetail(
                "Plan nie obejmuje kolejnego języka (limit poza pierwszym: "
                f"{limit.additional_max}). Więcej daje wyższy plan; usunąć język można zawsze.",
                code=QUOTA_EXCEEDED,
            )
        )
    if problems:
        raise ValidationError({field: problems})
    changed = after != before
    return PublicLocalesPlan(
        before=before,
        after=after,
        version=organization.public_locales_version + (1 if changed else 0),
        limit=limit,
    )


def _limit(organization: Organization) -> PublicLocalesLimit:
    """The plan's word on adding a language. The platform's workspace is
    exempt: the operator runs its languages (ADR-071 pkt 7)."""
    if organization.workspace_kind == WorkspaceKind.PLATFORM:
        return PublicLocalesLimit(allowed=True)
    decisions = [limit() for limit in tuple(_limits)]
    denied = next((decision for decision in decisions if not decision.allowed), None)
    if denied is not None:
        return denied
    maxima = [d.additional_max for d in decisions if d.additional_max is not None]
    return PublicLocalesLimit(allowed=True, additional_max=min(maxima) if maxima else None)


def _protected(organization: Organization, codes: frozenset[str]) -> dict[str, str]:
    if not codes:
        return {}
    found: dict[str, str] = {}
    for guard in tuple(_guards):
        for code, problem in guard(organization.id, codes).items():
            found.setdefault(code, problem)
    return found


def _save(
    organization: Organization,
    plan: PublicLocalesPlan,
    *,
    origin: str,
    actor_id: UUID | None,
    key: str,
    request_hash: str,
) -> PublicLocalesChange:
    organization.public_locales = list(plan.after)
    organization.public_locales_version = plan.version
    organization.save(update_fields=["public_locales", "public_locales_version", "updated_at"])
    actor = User.objects.filter(pk=actor_id).first() if actor_id is not None else None
    change = PublicLocalesChange.objects.create(
        organization=organization,
        version=plan.version,
        before=list(plan.before),
        after=list(plan.after),
        origin=origin,
        actor_user=actor,
        idempotency_key=key,
        request_hash=request_hash,
    )
    record_audit(
        organization=organization,
        action=OrganizationAuditAction.SETTINGS_CHANGED,
        actor=actor,
        target_type=PUBLIC_LOCALES_GROUP,
        target_id=organization.id,
        metadata={
            "field_changes": {
                "public_locales": {"from": list(plan.before), "to": list(plan.after)}
            },
            "origin": origin,
            "version": plan.version,
        },
    )
    for handler in tuple(_changed):
        handler(organization, plan.before, plan.after)
    return change


def _idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 120:
        raise ValidationError({
            "idempotency_key": [
                ErrorDetail("Nagłówek Idempotency-Key jest wymagany (do 120 znaków).", "required")
            ]
        })
    return normalized
