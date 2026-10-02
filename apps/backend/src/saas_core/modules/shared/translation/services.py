"""Translation settings, the glossary and the offer (ADR-069 pkt 6, 7, 12, 14, 28; ADR-078).

The panel and the assistant call these same functions. Every write carries an
idempotency key whose receipt is a `TranslationMutation`, applies only at the
version its caller saw (409 `translation_version_conflict`) and runs as a
preview with nothing saved — the same code in a rolled-back savepoint, so a
preview refuses exactly what the write would. `null` or an absent field means
"no change"; going back to the inherited value is the explicit `reset` list.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    ErrorDetail,
    NotFound,
    ParseError,
    ValidationError,
)

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import field_changes, record_audit
from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.core.organizations.canonical import canonical_json_hash
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.person_gate import assert_person_required
from saas_core.modules.core.organizations.platform_workspace import is_platform_workspace
from saas_core.modules.shared.billing.models import CreditOperation
from saas_core.modules.shared.model_port.api import task_status

from .engine_policy import ceiling_state, effective_mode, operator_override
from .glossary import GLOSSARY_LIMIT, GlossaryEntry, entry_problems
from .models import GlossaryRule, TranslationGlossaryTerm, TranslationMutation, TranslationSettings
from .permissions import CREDIT_OPERATION, TRANSLATION_MANAGE, TRANSLATION_REQUEST
from .prompts import TASK
from .quotes import UNIT_CHARACTERS
from .settings_spec import (
    AUTO_CHANGES,
    AUTO_MONTHLY_LIMIT,
    COMPANY_SETTINGS,
    DECLARATIONS,
    MODE,
    profile_default,
)

SETTINGS_GROUP = "translation.settings"
PROCESSING_ACK = "translation.settings.processing_acknowledged"

#: Person-only labels (`assert_person_required`).
AUTOMATION_CONSENT = "Zgoda na automat tłumaczeń"
PROCESSING_ACKNOWLEDGEMENT = "Potwierdzenie przetwarzania treści przez dostawców AI"

# Why translation cannot be ordered now (ADR-069 pkt 28).
UNAVAILABLE_OPERATION_UNPRICED = "operation_unpriced"
UNAVAILABLE_WORKER = "worker_unavailable"
UNAVAILABLE_DISABLED = "disabled"
UNAVAILABLE_SUSPENDED = "suspended"
UNAVAILABLE_PROCESSING_ACK = "processing_ack_required"


class TranslationIdempotencyConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Ten Idempotency-Key był użyty do innego żądania."
    default_code = "translation_idempotency_conflict"


class TranslationVersionConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Ktoś zmienił to w międzyczasie. Odśwież i spróbuj ponownie."
    default_code = "translation_version_conflict"


@dataclass(frozen=True, slots=True)
class Saved[T]:
    value: T
    item_id: UUID
    # After the write — for a preview, after it would be.
    version: int
    created: bool
    # `{field: {"from", "to"}}`, as the history keeps it.
    changes: dict[str, Any] = field(default_factory=dict)
    replayed: bool = False


class _Previewed(Exception):
    def __init__(self, saved: Saved[Any]) -> None:
        super().__init__()
        self.saved = saved


def translation_write[T](
    *,
    context: TenantContext,
    action: str,
    target_id: UUID | None,
    request: Mapping[str, Any],
    idempotency_key: str,
    preview: bool,
    write: Callable[[], Saved[T]],
    replay: Callable[[UUID], Saved[T]],
) -> Saved[T]:
    """One write under its key (`booking.setup.setup_write`'s semantics)."""
    if preview:
        try:
            with transaction.atomic():
                raise _Previewed(write())
        except _Previewed as done:
            return done.saved
    key = idempotency_key.strip()
    if not key or len(key) > 160:
        raise ParseError("Wymagany jest prawidłowy Idempotency-Key.")
    principal_ref = str(context.credential_id or context.actor_id)
    request_hash = canonical_json_hash(
        json.loads(
            json.dumps({"action": action, "target_id": target_id, **request}, cls=DjangoJSONEncoder)
        )
    )
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [f"translation:{context.organization_id}:{principal_ref}:{action}:{key}"],
            )
        receipt = TranslationMutation.all_objects.filter(
            organization_id=context.organization_id,
            action=action,
            principal_ref=principal_ref,
            idempotency_key=key,
        ).first()
        if receipt is not None:
            if receipt.request_hash != request_hash:
                raise TranslationIdempotencyConflict
            return replay(receipt.result_id)
        saved = write()
        TranslationMutation.all_objects.create(
            organization_id=context.organization_id,
            action=action,
            principal_ref=principal_ref,
            idempotency_key=key,
            request_hash=request_hash,
            result_id=saved.item_id,
        )
        return saved


#: What a person reads beside a field code; the code is what a caller acts on.
_MESSAGES = {
    "unknown_setting": "Nie ma takiego ustawienia.",
    "invalid_choice": "Wybierz jedną z dozwolonych wartości.",
    "invalid": "Nieprawidłowa wartość.",
    "out_of_range": "Wartość spoza dozwolonego zakresu.",
    "only_true": "To potwierdzenie można tylko włączyć.",
    "reset_conflict": "Nie można jednocześnie zmienić i przywrócić tego ustawienia.",
    "locale_not_in_registry": "Tego języka nie ma na platformie.",
    "same_as_source": "Język docelowy musi być inny niż źródłowy.",
    "not_for_rule": "Tłumaczenie podaje się tylko dla reguły „tłumacz jako”.",
    "glossary_term_exists": "Ten termin już jest w glosariuszu.",
    "glossary_limit_reached": "Glosariusz ma już najwięcej terminów (500).",
    "glossary_term_empty": "Wpisz termin.",
    "glossary_term_too_long": "Termin może mieć najwyżej 120 znaków.",
    "glossary_term_forbidden_characters": (
        "Termin to jedna linia bez znaków sterujących i znaczników."
    ),
    "glossary_translation_required": "Podaj tłumaczenie terminu.",
    "glossary_too_many_forms": "Podaj najwyżej 10 form.",
}


def field_errors(errors: Mapping[str, str]) -> ValidationError:
    """A 400 whose `errors` carry the field and its code (A1a)."""
    return ValidationError({
        name: [ErrorDetail(_MESSAGES.get(code, _MESSAGES["invalid"]), code=code)]
        for name, code in errors.items()
    })


def _check_version(current: int, expected: int | None) -> None:
    if expected is None:
        raise ValidationError(
            {"expected_version": "Podaj wersję, którą zmieniasz."}, code="required"
        )
    if current != expected:
        raise TranslationVersionConflict


def _actor(context: TenantContext) -> User | None:
    return User.objects.filter(pk=context.actor_id).first()


# --- Settings ---------------------------------------------------------------------


def _settings_row(organization_id: UUID, *, lock: bool = False) -> TranslationSettings | None:
    rows = TranslationSettings.all_objects.filter(organization_id=organization_id)
    return (rows.select_for_update() if lock else rows).first()


def settings_state(organization_id: UUID) -> dict[str, Any]:
    """Values with their source and locks, the version token, and the consents."""
    row = _settings_row(organization_id)
    override = operator_override(organization_id)
    effective = effective_mode(organization_id)
    defaults = settings.SETTINGS_DEFAULTS
    limit_own = row.auto_monthly_limit if row is not None else None
    limit_default = profile_default(defaults, AUTO_MONTHLY_LIMIT)
    limit = limit_own if limit_own is not None else limit_default
    limit_cap = override.auto_monthly_limit_cap if override is not None else None
    if limit_cap is not None:
        limit = min(limit, limit_cap)
    auto_own = row.auto_changes if row is not None else None
    auto = auto_own if auto_own is not None else profile_default(defaults, AUTO_CHANGES)
    mode_locked = effective.source in ("operator", "platform")
    return {
        "group": SETTINGS_GROUP,
        "version": row.version if row is not None else 0,
        "values": {
            MODE.key: {
                "value": (row.mode or None) if row is not None else None,
                "effective": effective.mode,
                "source": effective.source,
                "locked": mode_locked,
                "lock_reason": effective.reason if mode_locked else None,
                "operator_reason": override.reason if override and override.mode_cap else None,
            },
            AUTO_CHANGES.key: {
                "value": auto_own,
                "effective": bool(auto) and limit > 0,
                "source": "organization" if auto_own is not None else "code",
                "locked": False,
                "lock_reason": None,
                "operator_reason": None,
            },
            AUTO_MONTHLY_LIMIT.key: {
                "value": limit_own,
                "effective": limit,
                "source": "operator"
                if limit_cap is not None and limit == limit_cap
                else ("organization" if limit_own is not None else "code"),
                "locked": limit_cap is not None,
                "lock_reason": "operator_cap" if limit_cap is not None else None,
                "operator_reason": override.reason
                if override and override.auto_monthly_limit_cap is not None
                else None,
            },
        },
        "automation": {
            "consent_membership_id": row.auto_consent_membership_id if row else None,
            "consent_at": row.auto_consent_at if row else None,
        },
        "processing_acknowledged": bool(row and row.processing_ack_at),
        "processing_ack_at": row.processing_ack_at if row else None,
    }


def read_settings() -> dict[str, Any]:
    context = authorize(TRANSLATION_REQUEST)
    return settings_state(context.organization_id)


def _validate_settings(changes: Mapping[str, Any], reset: Sequence[str]) -> dict[str, str]:
    errors: dict[str, str] = {}
    keys = {declaration.key for declaration in COMPANY_SETTINGS}
    for key in changes:
        if key not in keys and key != PROCESSING_ACK:
            errors[key] = "unknown_setting"
    mode = changes.get(MODE.key)
    if mode is not None and mode not in MODE.variants:
        errors[MODE.key] = "invalid_choice"
    auto = changes.get(AUTO_CHANGES.key)
    if auto is not None and not isinstance(auto, bool):
        errors[AUTO_CHANGES.key] = "invalid"
    limit = changes.get(AUTO_MONTHLY_LIMIT.key)
    if limit is not None and (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not (AUTO_MONTHLY_LIMIT.minimum or 0) <= limit <= (AUTO_MONTHLY_LIMIT.maximum or 0)
    ):
        errors[AUTO_MONTHLY_LIMIT.key] = "out_of_range"
    ack = changes.get(PROCESSING_ACK)
    if ack is not None and ack is not True:
        errors[PROCESSING_ACK] = "only_true"
    for index, key in enumerate(reset):
        if key not in keys:
            errors[f"reset.{index}"] = "unknown_setting"
        elif changes.get(key) is not None:
            errors[f"reset.{index}"] = "reset_conflict"
    return errors


def change_settings(
    *,
    changes: Mapping[str, Any],
    reset: Sequence[str] | None = None,
    expected_version: int | None,
    idempotency_key: str = "",
    preview: bool = False,
) -> Saved[dict[str, Any]]:
    """Changes the company's translation settings (`translation.manage`).

    Turning the automation on is the consent of the person doing it: they
    become the person it acts as. The one-off acknowledgement that content
    goes to OpenRouter is recorded the same way, and only ever turned on.
    """
    context = authorize(TRANSLATION_MANAGE)
    reset_keys = list(dict.fromkeys(reset or ()))
    errors = _validate_settings(changes, reset_keys)
    if errors:
        raise field_errors(errors)
    organization = Organization.objects.get(pk=context.organization_id)

    def write() -> Saved[dict[str, Any]]:
        row = _settings_row(organization.id, lock=True)
        created = row is None
        if row is None:
            row = TranslationSettings.all_objects.create(organization=organization)
        _check_version(row.version, expected_version)
        before = {
            "mode": row.mode,
            "auto_changes": row.auto_changes,
            "auto_monthly_limit": row.auto_monthly_limit,
        }
        acknowledged = row.processing_ack_at is not None
        now = timezone.now()
        if changes.get(MODE.key) is not None:
            row.mode = changes[MODE.key]
        if changes.get(AUTO_MONTHLY_LIMIT.key) is not None:
            row.auto_monthly_limit = changes[AUTO_MONTHLY_LIMIT.key]
        auto = changes.get(AUTO_CHANGES.key)
        if auto is True and row.auto_changes is not True:
            # Consent is one person's act: never an API key, a job or the
            # assistant on its own (it opens this only after a click, TL6c).
            assert_person_required(context, AUTOMATION_CONSENT)
            row.auto_consent_membership_id = context.membership_id
            row.auto_consent_at = now
        if auto is not None:
            row.auto_changes = auto
        if changes.get(PROCESSING_ACK) is True and row.processing_ack_at is None:
            assert_person_required(context, PROCESSING_ACKNOWLEDGEMENT)
            row.processing_ack_membership_id = context.membership_id
            row.processing_ack_at = now
        for key in reset_keys:
            if key == MODE.key:
                row.mode = ""
            elif key == AUTO_CHANGES.key:
                row.auto_changes = None
            elif key == AUTO_MONTHLY_LIMIT.key:
                row.auto_monthly_limit = None
        if row.auto_changes is False:
            row.auto_consent_membership_id, row.auto_consent_at = None, None
        after = {
            "mode": row.mode,
            "auto_changes": row.auto_changes,
            "auto_monthly_limit": row.auto_monthly_limit,
        }
        diff = field_changes(before, after)
        if not acknowledged and row.processing_ack_at is not None:
            diff["processing_acknowledged"] = {"from": False, "to": True}
        if diff or created:
            row.version += 1
            row.save()
            record_audit(
                organization=organization,
                action="translation.settings_changed",
                actor=_actor(context),
                target_type=SETTINGS_GROUP,
                target_id=row.id,
                metadata={"group": SETTINGS_GROUP, "changes": diff, "version": row.version},
            )
        return Saved(
            value=settings_state(organization.id),
            item_id=row.id,
            version=row.version,
            created=created,
            changes=diff,
        )

    def replay(_row_id: UUID) -> Saved[dict[str, Any]]:
        state = settings_state(organization.id)
        return Saved(state, _row_id, state["version"], created=False, replayed=True)

    return translation_write(
        context=context,
        action="settings.update",
        target_id=None,
        request={
            "changes": dict(changes),
            "reset": reset_keys,
            "expected_version": expected_version,
        },
        idempotency_key=idempotency_key,
        preview=preview,
        write=write,
        replay=replay,
    )


# --- Glossary -----------------------------------------------------------------------


def list_glossary(
    *, cursor: str | None, limit: int
) -> tuple[list[TranslationGlossaryTerm], str | None]:
    context = authorize(TRANSLATION_REQUEST)
    terms = TranslationGlossaryTerm.all_objects.filter(
        organization_id=context.organization_id
    ).order_by("source_locale", "term", "id")
    start = int(cursor) if cursor and cursor.isdigit() else 0
    page = list(terms[start : start + limit + 1])
    next_cursor = str(start + limit) if len(page) > limit else None
    return page[:limit], next_cursor


def _validate_term(data: Mapping[str, Any]) -> GlossaryEntry:
    entry = GlossaryEntry(
        term=str(data.get("term", "")).strip(),
        rule=str(data.get("rule", "")),
        source_locale=str(data.get("source_locale", "")),
        target_locale=str(data.get("target_locale") or ""),
        translation=str(data.get("translation") or "").strip(),
        forms=tuple(str(form).strip() for form in data.get("forms") or ()),
    )
    errors: dict[str, str] = dict(entry_problems(entry))
    if entry.rule not in GlossaryRule.values:
        errors["rule"] = "invalid_choice"
    known = settings.LOCALE_REGISTRY
    if entry.source_locale not in known:
        errors["source_locale"] = "locale_not_in_registry"
    if entry.target_locale and entry.target_locale not in known:
        errors["target_locale"] = "locale_not_in_registry"
    if entry.target_locale and entry.target_locale == entry.source_locale:
        errors["target_locale"] = "same_as_source"
    if entry.rule != GlossaryRule.TRANSLATE_AS and entry.translation:
        errors["translation"] = "not_for_rule"
    if errors:
        raise field_errors(errors)
    return entry


def _apply_term(term: TranslationGlossaryTerm, entry: GlossaryEntry) -> None:
    term.term = entry.term
    term.rule = entry.rule
    term.source_locale = entry.source_locale
    term.target_locale = entry.target_locale
    term.translation = entry.translation
    term.forms = list(entry.forms)


def _term_snapshot(term: TranslationGlossaryTerm) -> dict[str, Any]:
    # Not the term's words: a `name` term is a person's name.
    return {
        "rule": term.rule,
        "source_locale": term.source_locale,
        "target_locale": term.target_locale,
        "forms": len(term.forms),
    }


def _save_term(term: TranslationGlossaryTerm) -> None:
    try:
        with transaction.atomic():
            term.save()
    except IntegrityError as error:
        if "translation_glossary_term_unique" in str(error):
            raise field_errors({"term": "glossary_term_exists"}) from error
        raise


def create_glossary_term(
    *, data: Mapping[str, Any], idempotency_key: str = "", preview: bool = False
) -> Saved[TranslationGlossaryTerm]:
    context = authorize(TRANSLATION_MANAGE)
    entry = _validate_term(data)
    organization = Organization.objects.get(pk=context.organization_id)

    def write() -> Saved[TranslationGlossaryTerm]:
        count = TranslationGlossaryTerm.all_objects.filter(organization=organization).count()
        if count >= GLOSSARY_LIMIT:
            raise field_errors({"term": "glossary_limit_reached"})
        term = TranslationGlossaryTerm(organization=organization)
        _apply_term(term, entry)
        _save_term(term)
        record_audit(
            organization=organization,
            action="translation.glossary_term_created",
            actor=_actor(context),
            target_type="translation.glossary_term",
            target_id=term.id,
            metadata=_term_snapshot(term),
        )
        return Saved(term, term.id, term.version, created=True)

    def replay(term_id: UUID) -> Saved[TranslationGlossaryTerm]:
        term = TranslationGlossaryTerm.all_objects.get(pk=term_id)
        return Saved(term, term.id, term.version, created=True, replayed=True)

    return translation_write(
        context=context,
        action="glossary.create",
        target_id=None,
        request=dict(data),
        idempotency_key=idempotency_key,
        preview=preview,
        write=write,
        replay=replay,
    )


def _locked_term(organization: Organization, term_id: UUID) -> TranslationGlossaryTerm:
    term = (
        TranslationGlossaryTerm.all_objects.select_for_update()
        .filter(organization=organization, pk=term_id)
        .first()
    )
    if term is None:
        raise NotFound("Nie ma takiego terminu.")
    return term


def update_glossary_term(
    *,
    term_id: UUID,
    data: Mapping[str, Any],
    expected_version: int | None,
    idempotency_key: str = "",
    preview: bool = False,
) -> Saved[TranslationGlossaryTerm]:
    context = authorize(TRANSLATION_MANAGE)
    organization = Organization.objects.get(pk=context.organization_id)

    def write() -> Saved[TranslationGlossaryTerm]:
        term = _locked_term(organization, term_id)
        _check_version(term.version, expected_version)
        current = {
            "term": term.term,
            "rule": term.rule,
            "source_locale": term.source_locale,
            "target_locale": term.target_locale,
            "translation": term.translation,
            "forms": list(term.forms),
        }
        merged = {**current, **{key: value for key, value in data.items() if value is not None}}
        entry = _validate_term(merged)
        before = _term_snapshot(term)
        _apply_term(term, entry)
        diff = field_changes(current, {**current, **merged})
        if diff:
            term.version += 1
            _save_term(term)
            record_audit(
                organization=organization,
                action="translation.glossary_term_updated",
                actor=_actor(context),
                target_type="translation.glossary_term",
                target_id=term.id,
                metadata={**_term_snapshot(term), "fields": sorted(diff), "before": before},
            )
        return Saved(term, term.id, term.version, created=False, changes=diff)

    def replay(_term_id: UUID) -> Saved[TranslationGlossaryTerm]:
        term = TranslationGlossaryTerm.all_objects.get(pk=_term_id)
        return Saved(term, term.id, term.version, created=False, replayed=True)

    return translation_write(
        context=context,
        action="glossary.update",
        target_id=term_id,
        request={**dict(data), "expected_version": expected_version},
        idempotency_key=idempotency_key,
        preview=preview,
        write=write,
        replay=replay,
    )


def delete_glossary_term(
    *, term_id: UUID, expected_version: int | None, idempotency_key: str = ""
) -> Saved[None]:
    context = authorize(TRANSLATION_MANAGE)
    organization = Organization.objects.get(pk=context.organization_id)

    def write() -> Saved[None]:
        term = _locked_term(organization, term_id)
        _check_version(term.version, expected_version)
        snapshot = _term_snapshot(term)
        term.delete()
        record_audit(
            organization=organization,
            action="translation.glossary_term_deleted",
            actor=_actor(context),
            target_type="translation.glossary_term",
            target_id=term_id,
            metadata=snapshot,
        )
        return Saved(None, term_id, 0, created=False)

    def replay(_term_id: UUID) -> Saved[None]:
        return Saved(None, _term_id, 0, created=False, replayed=True)

    return translation_write(
        context=context,
        action="glossary.delete",
        target_id=term_id,
        request={"expected_version": expected_version},
        idempotency_key=idempotency_key,
        preview=False,
        write=write,
        replay=replay,
    )


# --- The offer ---------------------------------------------------------------------


def translation_offer() -> dict[str, Any]:
    """Whether the company can order a translation now, why not, and on what terms."""
    context = authorize(TRANSLATION_REQUEST)
    organization = Organization.objects.get(pk=context.organization_id)
    platform = is_platform_workspace(organization)
    state = settings_state(organization.id)
    reasons: list[str] = []
    port = task_status(TASK)
    if port.reason is not None:
        reasons.append(port.reason)
    operation = CreditOperation.objects.filter(key=CREDIT_OPERATION).first()
    unit_cost = operation.cost if operation is not None and operation.is_active else None
    if unit_cost is None and not platform:
        reasons.append(UNAVAILABLE_OPERATION_UNPRICED)
    if ceiling_state() == "off":
        reasons.append(UNAVAILABLE_DISABLED)
    override = operator_override(organization.id)
    if override is not None and override.mode_cap == "off":
        reasons.append(UNAVAILABLE_SUSPENDED)
    if not platform and not state["processing_acknowledged"]:
        reasons.append(UNAVAILABLE_PROCESSING_ACK)
    # Jobs and their worker arrive with TL6b.
    reasons.append(UNAVAILABLE_WORKER)
    return {
        "available": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "mode": state["values"][MODE.key],
        "automation": {
            **state["automation"],
            "enabled": state["values"][AUTO_CHANGES.key]["effective"],
            "monthly_limit": state["values"][AUTO_MONTHLY_LIMIT.key]["effective"],
        },
        "billing": {
            "mode": "platform_budget" if platform else "credits",
            "operation_key": CREDIT_OPERATION,
            "unit_characters": UNIT_CHARACTERS,
            "credits_per_unit": unit_cost,
        },
        "settings": [declaration.as_dict() for declaration in DECLARATIONS.values()],
        "glossary_limit": GLOSSARY_LIMIT,
    }
