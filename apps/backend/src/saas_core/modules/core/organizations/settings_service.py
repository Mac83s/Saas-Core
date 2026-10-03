"""Reading and changing a company's settings (ADR-078 pkt 3, 7, 9).

`resolve(key)` is the only way code reads a setting: the company's own value,
else the platform's, else the code's — with the source. Each read asks the
database (one small query: the company's rows); code that reads many times in
a loop wraps it in `settings_snapshot()`, which reads them once for the block
and forgets them on a change. A cache tied to the request would outlive a
consent's preview into its run and hide the change that made it stale.

`change_settings(group, …)` is the one write: permission, the plan's feature,
validation by the declaration, a preview of what the change does, the group's
version token, a receipt for the idempotency key, one history row (with
"on behalf of", ADR-076 §6) and the group's own reaction, in one transaction.
`null` (or a field left out) changes nothing; going back to the default is the
explicit `reset` list.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import APIException, ErrorDetail, NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.identity.step_up import require_step_up

from .audit import record_audit
from .authorization import authorize
from .canonical import canonical_json_hash
from .command_registry import Effect
from .context import TenantContext, current_tenant_context
from .models import (
    Organization,
    OrganizationAuditAction,
    OrganizationSetting,
    OrganizationSettingsReceipt,
)
from .permissions import ORGANIZATION_READ
from .settings_registry import (
    SettingGroup,
    SettingSpec,
    check_value,
    live_product_value,
    organization_groups,
    platform_group,
    platform_value,
    product_value,
    registered_groups,
    setting_group,
    setting_spec,
)

#: `feature(key, write)` → the plan's refusal reason, or None. Billing
#: registers it; a profile without billing has no plan to ask.
FeatureCheck = Callable[[str, bool], str | None]
_feature_checks: list[FeatureCheck] = []


def register_settings_feature_check(check: FeatureCheck) -> None:
    if check not in _feature_checks:
        _feature_checks.append(check)


class SettingsVersionConflict(APIException):
    status_code = 409
    default_detail = "Ustawienia zmieniły się w międzyczasie. Odśwież je i spróbuj ponownie."
    default_code = "settings_version_conflict"


class SettingsIdempotencyConflict(APIException):
    status_code = 409
    default_detail = "Ten klucz idempotencji użyto już dla innej zmiany ustawień."
    default_code = "settings_idempotency_conflict"


class SettingsEntitlementRequired(APIException):
    status_code = 403
    default_detail = "Plan firmy nie obejmuje tych ustawień."
    default_code = "entitlement_required"


@dataclass(frozen=True, slots=True)
class Resolved:
    value: Any
    #: `code`, `platform`, `product` or `organization` (ADR-078 pkt 3).
    source: str


@dataclass(frozen=True, slots=True)
class GroupState:
    group: SettingGroup
    #: By field: the value that applies and where it comes from.
    values: Mapping[str, Resolved]
    version: str
    can_change: bool
    #: Why the company cannot change the group now (the plan), or "".
    locked: str


@dataclass(frozen=True, slots=True)
class SettingsChange:
    before: GroupState
    #: The values after the change, by field (all of them).
    after: Mapping[str, Any]
    #: Only the fields whose value changes: {field: {"from", "to"}}.
    changes: Mapping[str, Mapping[str, Any]]
    effects: tuple[Effect, ...]
    #: The token after the change; the same for a preview or a change of nothing.
    version: str
    #: A repeat of an earlier request: the stored answer.
    replayed: Mapping[str, Any] | None = None


# --- reading --------------------------------------------------------------------------

_snapshot: ContextVar[dict[UUID, dict[str, OrganizationSetting]] | None] = ContextVar(
    "organization_settings_snapshot", default=None
)


@contextmanager
def settings_snapshot() -> Iterator[None]:
    """Reads the company's values once for the block (a loop over many visits)."""
    token = _snapshot.set({})
    try:
        yield
    finally:
        _snapshot.reset(token)


def resolve(key: str, *, organization_id: UUID | None = None) -> Resolved:
    """The value of `key` for the company of the current tenant context — or of
    `organization_id`, for work that runs per company (a sweep) with that
    company's tenant set, so row-level security lets its rows through.

    A `restrict` setting's value in force may be stricter: its module applies
    its own ceilings on top (ADR-078 pkt 3)."""
    spec = setting_spec(key)
    group = setting_group(spec.group)
    if platform_group(group):
        # No company has a say: the platform's value, without a tenant.
        explicit = None
    elif group.api is not None:
        if group.read_explicit is None:
            raise LookupError(f"{key}: wartość węższego zasięgu czyta jej moduł.")
        explicit = group.read_explicit().get(spec.field)
    else:
        row = _rows(organization_id).get(key)
        explicit = _presented(spec, row.value, organization_id) if row is not None else None
    if explicit is not None:
        return Resolved(explicit, "organization")
    product = live_product_value(spec)
    if product is not None:
        return Resolved(product, "product")
    platform = platform_value(spec)
    if platform is not None:
        return Resolved(platform, "platform")
    return Resolved(spec.default, "code")


def setting(key: str, *, organization_id: UUID | None = None) -> Any:
    return resolve(key, organization_id=organization_id).value


def inherited(key: str) -> Resolved:
    """What a company without a value of its own gets for `key`, and from
    where: the product's default, the platform's value, the code's — the
    registry's order below the company (ADR-078 pkt 3). For a module that
    keeps the company's values in its own table and reads them where there is
    no tenant context to give `resolve()` (a sweep): it reads its row, then
    asks here, and does not rebuild the order."""
    spec = setting_spec(key)
    product = live_product_value(spec)
    if product is not None:
        return Resolved(product, "product")
    platform = platform_value(spec)
    if platform is not None:
        return Resolved(platform, "platform")
    return Resolved(spec.default, "code")


def read_group(group_key: str) -> GroupState:
    context = authorize(ORGANIZATION_READ)
    return _state(context, _group(context, group_key))


def _state(context: TenantContext, group: SettingGroup) -> GroupState:
    rows = _rows()
    locked = group_locked(group)
    return GroupState(
        group=group,
        values={spec.field: resolve(spec.key) for spec in group.settings},
        version=_token(group, rows),
        can_change=_may_change(context, group) and not locked,
        locked=locked,
    )


def schema(context: TenantContext) -> list[tuple[SettingGroup, bool, str]]:
    """Each group the company has, whether this person may change it, and why
    not when the plan says no."""
    return [
        (
            group,
            _may_change(context, group) and not group_locked(group),
            group_locked(group),
        )
        for group in organization_groups(context.organization_id)
        # The platform's own groups are the operators', in „Platforma”.
        if not platform_group(group)
    ]


def settings_at_creation(organization: Organization) -> None:
    """A new company's own values of the keys copied at creation (ADR-078
    pkt 6) — the product's value, written as if the company had chosen it.
    The caller has set the new company's tenant."""
    OrganizationSetting.objects.bulk_create([
        OrganizationSetting(organization=organization, key=spec.key, value=value)
        for group in registered_groups()
        if group.api is None
        for spec in group.settings
        if spec.inheritance == "copy_at_creation" and (value := product_value(spec)) is not None
    ])


# --- changing -------------------------------------------------------------------------


@transaction.atomic
def change_settings(
    group_key: str,
    *,
    changes: Mapping[str, Any],
    reset: Sequence[str] = (),
    expected_version: str,
    idempotency_key: str = "",
    preview: bool = False,
) -> SettingsChange:
    """Changes the company's values of one group, or — with `preview` — says
    what the change would do, with every problem the save would raise."""
    context = authorize(ORGANIZATION_READ)
    group = _group(context, group_key)
    context = authorize(group.permission, owner_only=group.owner_only)
    if reason := group_locked(group, write=True):
        raise SettingsEntitlementRequired(detail=_DENIALS.get(reason, reason))
    if group.step_up_reason and not preview:
        # Who may first, then the code: nobody is asked for a code in vain.
        require_step_up(user_id=context.actor_id, reason=group.step_up_reason)
    given = {name: value for name, value in changes.items() if value is not None}
    resetting = tuple(dict.fromkeys(reset))
    request_hash = canonical_json_hash({
        "group": group.key,
        "changes": given,
        "reset": sorted(resetting),
        "expected_version": expected_version,
    })
    key = "" if preview else _idempotency_key(idempotency_key)
    # One writer at a time per company: the token is read and moved under it.
    organizations = Organization.objects.all()
    if not preview:
        organizations = organizations.select_for_update()
    organization = organizations.get(pk=context.organization_id)
    principal = str(context.membership_id or context.actor_id)
    if key:
        done = OrganizationSettingsReceipt.objects.filter(
            organization_id=organization.id,
            group=group.key,
            principal_ref=principal,
            idempotency_key=key,
        ).first()
        if done is not None:
            if done.request_hash != request_hash:
                raise SettingsIdempotencyConflict
            before = _state(context, group)
            return SettingsChange(
                before=before,
                after=done.result.get("values", {}),
                changes=done.result.get("changes", {}),
                effects=(),
                version=done.result.get("version", before.version),
                replayed=done.result,
            )
    _forget(context.organization_id)
    before = _state(context, group)
    if before.version != expected_version:
        raise SettingsVersionConflict
    after_explicit = _validated(
        group,
        given,
        resetting,
        company_locales=tuple(organization.public_locales),
        in_force={field: resolved.value for field, resolved in before.values.items()},
    )
    after = {
        spec.field: (
            after_explicit[spec.field]
            if spec.field in after_explicit and after_explicit[spec.field] is not None
            else _inherited(spec)
        )
        for spec in group.settings
    }
    current = {field: resolved.value for field, resolved in before.values.items()}
    changed = {
        field: {"from": current[field], "to": after[field]}
        for field in group.fields
        if after[field] != current[field]
    }
    if group.check and changed and (refused := group.check(current, after)):
        raise ValidationError({
            field: [ErrorDetail(message, code)] for field, (message, code) in refused.items()
        })
    touched = [
        spec
        for spec in group.settings
        if spec.field in after_explicit and _explicit(spec) != after_explicit[spec.field]
    ]
    effects = group.effects(current, after) if group.effects and changed else ()
    if preview or not touched:
        return SettingsChange(
            before=before, after=after, changes=changed, effects=effects, version=before.version
        )
    actor = User.objects.filter(pk=context.actor_id).first()
    _save(organization, touched, after_explicit, actor)
    version = _token(group, _rows())
    record_audit(
        organization=organization,
        action=OrganizationAuditAction.SETTINGS_CHANGED,
        actor=actor,
        target_type=group.key,
        target_id=organization.id,
        metadata={
            "fields": sorted(spec.field for spec in touched),
            "changes": {
                field: ({"changed": True} if group.spec(field).data_class == "personal" else change)
                for field, change in changed.items()
            },
            "reset": sorted(resetting),
            "version": version,
        },
    )
    if group.on_changed and changed:
        group.on_changed(current, after)
    result = {"values": after, "changes": changed, "version": version}
    if key:
        OrganizationSettingsReceipt.objects.create(
            organization=organization,
            group=group.key,
            principal_ref=principal,
            idempotency_key=key,
            request_hash=request_hash,
            result=result,
        )
    return SettingsChange(
        before=before, after=after, changes=changed, effects=effects, version=version
    )


_DENIALS = {
    "feature_disabled": "Plan firmy nie obejmuje tej funkcji.",
    "read_only": "Subskrypcja jest tylko do odczytu.",
    "access_blocked": "Dostęp do konta jest zablokowany.",
    "snapshot_expired": "Uprawnienia planu wygasły.",
    "snapshot_missing": "Firma nie ma jeszcze planu.",
}


def _group(context: TenantContext, group_key: str) -> SettingGroup:
    """A group core reads and changes itself; an entity group's own module does."""
    for group in organization_groups(context.organization_id):
        if group.key == group_key and group.api is None and not platform_group(group):
            return group
    raise NotFound("Nie ma takiej grupy ustawień.")


def validate_settings(
    group_key: str, changes: Mapping[str, Any], reset: Sequence[str] = ()
) -> dict[str, Any]:
    """The declaration's check of a change, for a module that writes its own
    group: values by field (None for each one reset), or a `ValidationError`
    with the same field codes as core's groups."""
    given = {name: value for name, value in changes.items() if value is not None}
    return _validated(setting_group(group_key), given, tuple(dict.fromkeys(reset)))


def _may_change(context: TenantContext, group: SettingGroup) -> bool:
    return context.has_permission(group.permission) and (
        not group.owner_only or context.role_key == "owner"
    )


def group_locked(group: SettingGroup, *, write: bool = False) -> str:
    if group.entitlement is None:
        return ""
    for check in tuple(_feature_checks):
        reason = check(group.entitlement, write)
        if reason:
            return reason
    return ""


def _validated(
    group: SettingGroup,
    given: Mapping[str, Any],
    reset: Sequence[str],
    *,
    company_locales: Sequence[str] | None = None,
    in_force: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The company's explicit values after the change, by field: a value for
    each one given, None for each one reset.

    A `localized_text` change is merged into the value in force, language by
    language: one left out (or null) stays, an empty text removes that
    language, and only `reset` clears the key — "set the German note" cannot
    wipe the Polish one. With `company_locales`, a text in a language the
    company does not have is refused (`locale_not_enabled`); a stored text of
    a language the company later removed stays, unused (UF-T5)."""
    problems: dict[str, list[ErrorDetail]] = {}
    explicit: dict[str, Any] = {}
    for name, value in given.items():
        if name not in group.fields:
            problems[name] = [ErrorDetail("Nie ma takiego ustawienia.", code="unknown_setting")]
            continue
        if group.spec(name).type == "localized_text" and isinstance(value, Mapping):
            wanted = {str(code): text for code, text in value.items() if text is not None}
            foreign = sorted(
                code
                for code, text in wanted.items()
                if company_locales is not None
                and code in settings.LOCALE_REGISTRY
                and code not in company_locales
                and isinstance(text, str)
                and text.strip()
            )
            if foreign:
                problems[name] = [
                    ErrorDetail(
                        f"Firma nie ma języka: {', '.join(foreign)}. Dodaj go w Ustawienia › "
                        "Języki.",
                        code="locale_not_enabled",
                    )
                ]
                continue
            if not wanted:
                # Every language left as it is (the assistant's all-null): no
                # change of this field, and no explicit empty map either.
                continue
            base = (in_force or {}).get(name)
            value = {**(base if isinstance(base, Mapping) else {}), **wanted}
        checked = check_value(group.spec(name), value)
        if checked is None or checked[1]:
            message, code = (checked[1], checked[2]) if checked else ("Zła wartość.", "invalid")
            problems[name] = [ErrorDetail(message, code=code)]
            continue
        explicit[name] = checked[0]
    for name in reset:
        if name not in group.fields:
            problems.setdefault("reset", []).append(
                ErrorDetail(f"Nie ma ustawienia {name}.", code="invalid_choice")
            )
        elif name in given:
            problems[name] = [
                ErrorDetail("Ustaw wartość albo przywróć domyślną, nie oba.", code="invalid")
            ]
        else:
            explicit[name] = None
    if problems:
        raise ValidationError(problems)
    return explicit


def _inherited(spec: SettingSpec) -> Any:
    for value in (live_product_value(spec), platform_value(spec)):
        if value is not None:
            return value
    return spec.default


def _explicit(spec: SettingSpec) -> Any:
    row = _rows().get(spec.key)
    return _presented(spec, row.value, None) if row is not None else None


def _presented(spec: SettingSpec, value: Any, organization_id: UUID | None) -> Any:
    """A stored value as its type reads it. A `localized_text` key that was a
    plain `text` before keeps the company's one text: it reads as the text of
    the company's first language, and is rewritten as a map on the next save —
    no sweep across tenants, and no mail without its note in between."""
    if spec.type != "localized_text" or not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return {}
    if organization_id is None:
        context = current_tenant_context()
        if context is None:
            raise RuntimeError("Ustawienia firmy czyta się w kontekście firmy.")
        organization_id = context.organization_id
    locales = (
        Organization.objects.filter(pk=organization_id)
        .values_list("public_locales", flat=True)
        .first()
    )
    return {locales[0]: text} if locales else {}


def _save(
    organization: Organization,
    specs: Sequence[SettingSpec],
    explicit: Mapping[str, Any],
    actor: User | None,
) -> None:
    for spec in specs:
        row, _ = OrganizationSetting.objects.get_or_create(organization=organization, key=spec.key)
        row.value = explicit[spec.field]
        row.version += 1
        row.updated_by = actor
        row.save(update_fields=["value", "version", "updated_by", "updated_at"])
    _forget(organization.id)


def _rows(organization_id: UUID | None = None) -> dict[str, OrganizationSetting]:
    if organization_id is None:
        context = current_tenant_context()
        if context is None:
            raise RuntimeError("Ustawienia firmy czyta się w kontekście firmy.")
        organization_id = context.organization_id
    snapshot = _snapshot.get()
    if snapshot is not None and organization_id in snapshot:
        return snapshot[organization_id]
    rows = {
        row.key: row for row in OrganizationSetting.objects.filter(organization_id=organization_id)
    }
    if snapshot is not None:
        snapshot[organization_id] = rows
    return rows


def _forget(organization_id: UUID) -> None:
    snapshot = _snapshot.get()
    if snapshot is not None:
        snapshot.pop(organization_id, None)


def _token(group: SettingGroup, rows: Mapping[str, OrganizationSetting]) -> str:
    """One version for the group: the versions of its rows (none = 0), hashed —
    another group's change does not stale this group's form."""
    observed = {
        spec.key: rows[spec.key].version if spec.key in rows else 0 for spec in group.settings
    }
    return canonical_json_hash(observed)[:16]


def _idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 120:
        raise ValidationError({
            "idempotency_key": [
                ErrorDetail("Nagłówek Idempotency-Key jest wymagany (do 120 znaków).", "required")
            ]
        })
    return normalized
