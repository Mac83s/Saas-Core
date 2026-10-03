"""Reading and saving the company's profile (A2).

A save keeps what the owner said and changes nothing in the account; no model
is called here. One row per saved state (`AssistantProfileVersion`), so the
history says who changed what and from which conversation.

The changes are a JSON merge patch (RFC 7396): a field sent replaces the
field, `null` removes it and a list is replaced whole. The profile belongs to
the company, not to one person's conversation, so it is read and changed by
whoever manages the company's settings — directly, or through the assistant
acting for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from saas_core.modules.core.organizations.api import canonical_json, canonical_json_hash
from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE
from saas_core.modules.shared.billing.api import FeatureOperation, decide_feature

from .models import AssistantProfileVersion
from .permissions import ASSISTANT_USE, TEXT_FEATURE
from .profile_schema import MAX_PROFILE_BYTES, empty_profile, validate_profile

_CONVERSATION = "conversation:"


class ProfileVersionConflict(APIException):
    status_code = 409
    default_detail = "Profil firmy zmienił się w międzyczasie. Odśwież go i spróbuj ponownie."
    default_code = "assistant_profile_version_conflict"


class ProfileKeyReused(APIException):
    status_code = 409
    default_detail = "Ten klucz Idempotency-Key był już użyty do innej zmiany profilu."
    default_code = "assistant_idempotency_conflict"


@dataclass(frozen=True, slots=True)
class ProfileState:
    #: 0 while nothing was saved; the document is then the empty profile.
    version: int
    document: dict[str, Any]
    updated_at: datetime | None
    #: What a save, or its preview, changed: `company.city`, `offers`.
    changed: tuple[str, ...] = ()


def read_profile() -> ProfileState:
    return _state(_latest(_manager(FeatureOperation.READ)))


@transaction.atomic
def save_profile(
    *,
    changes: dict[str, Any],
    expected_version: int,
    idempotency_key: str = "",
    preview: bool = False,
) -> ProfileState:
    """Applies the changes to the version the caller saw. A preview answers
    what the save would leave and writes nothing."""
    context = _manager(FeatureOperation.WRITE)
    request_hash = canonical_json_hash({"changes": changes, "expected_version": expected_version})
    if not preview:
        if not idempotency_key:
            raise ValidationError({"idempotency_key": "Zapis profilu wymaga klucza."})
        repeated = _versions(context).filter(idempotency_key=idempotency_key).first()
        if repeated is not None:
            if repeated.request_hash != request_hash:
                raise ProfileKeyReused
            return _state(repeated)
    current = _latest(context, lock=True)
    before = _state(current)
    if before.version != expected_version:
        raise ProfileVersionConflict
    document = _merged(before.document, changes)
    validate_profile(document)
    if len(canonical_json(document)) > MAX_PROFILE_BYTES:
        raise ValidationError({"changes": "Profil jest za długi."}, code="too_large")
    changed = tuple(_changed(before.document, document))
    if not changed:
        return before
    if preview:
        return ProfileState(before.version + 1, document, before.updated_at, changed)
    try:
        with transaction.atomic():
            saved = AssistantProfileVersion.all_objects.create(
                organization_id=context.organization_id,
                version=before.version + 1,
                document=document,
                created_by_id=context.actor_id,
                membership_id=context.membership_id,
                acting_via=context.acting_via,
                conversation_id=_conversation(context),
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
    except IntegrityError:
        # Two first saves at once: there was no row to lock.
        raise ProfileVersionConflict from None
    return ProfileState(saved.version, document, saved.created_at, changed)


def _manager(operation: FeatureOperation) -> TenantContext:
    authorize(ASSISTANT_USE)
    context = authorize(SETTINGS_MANAGE)
    if context.principal_kind != "membership":
        raise PermissionDenied(
            "Profil firmy zmienia osoba zalogowana w panelu.", code="assistant_person_only"
        )
    if not decide_feature(TEXT_FEATURE, operation=operation).allowed:
        raise PermissionDenied(
            "Asystent nie jest w planie tej firmy.", code="assistant_not_in_plan"
        )
    return context


def _versions(context: TenantContext) -> Any:
    return AssistantProfileVersion.all_objects.filter(organization_id=context.organization_id)


def _latest(context: TenantContext, *, lock: bool = False) -> AssistantProfileVersion | None:
    rows = _versions(context).order_by("-version")
    if lock:
        rows = rows.select_for_update()
    found: AssistantProfileVersion | None = rows.first()
    return found


def _state(row: AssistantProfileVersion | None) -> ProfileState:
    if row is None:
        return ProfileState(0, empty_profile(), None)
    return ProfileState(row.version, row.document, row.created_at)


def _conversation(context: TenantContext) -> UUID | None:
    if context.acting_via != "assistant" or not context.acting_ref.startswith(_CONVERSATION):
        return None
    return UUID(context.acting_ref.removeprefix(_CONVERSATION))


def _merged(target: Any, patch: Any) -> Any:
    """RFC 7396."""
    if not isinstance(patch, dict):
        return patch
    result = dict(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = _merged(result.get(key), value)
    return result


def _changed(before: Any, after: Any, path: str = "") -> list[str]:
    """The fields that differ, down to a value with its origin; a list counts
    as one field, as the merge replaces it whole."""
    if before == after:
        return []
    if not (_is_section(before) and _is_section(after)):
        return [path]
    before, after = before or {}, after or {}
    return [
        found
        for key in sorted({*before, *after})
        for found in _changed(before.get(key), after.get(key), f"{path}.{key}" if path else key)
    ]


def _is_section(node: Any) -> bool:
    """A group of fields, there or not yet — not a value with its origin."""
    return node is None or (isinstance(node, dict) and "origin" not in node)
