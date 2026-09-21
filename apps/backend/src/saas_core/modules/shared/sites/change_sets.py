"""Reading, checking and applying a ContentChangeSet (W9.6.6).

The document itself is frozen in `packages/contracts/content-operations` and
validated by both repositories against the same files. This module is the
receiving half: it decides whether a well-formed change set may take effect
here, now, on this resource, and what it would do if it did.

Preview does not mutate. `apply_change_set` calls the same domain services a
person's click calls, so an automation cannot reach a shortcut a human does not
have — which is the whole reason the commands are an allowlist rather than a
patch format.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core import signing
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from jsonschema import Draft202012Validator
from rest_framework.exceptions import APIException

from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .block_contracts import validate_site_block
from .block_decoration import normalize_block, stored_block_payload
from .capabilities import CONTENT_CONTRACT_VERSION, MINIMUM_CONTENT_CONTRACT_VERSION
from .metrics import (
    CHANGE_SET_LATENCY,
    CHANGE_SET_REFUSALS,
    CHANGE_SET_RESULTS,
)
from .models import (
    ContentEntry,
    ContentProposal,
    Page,
    PageBlock,
    PageTranslation,
    Site,
    canonical_json_hash,
)
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED


class ChangeSetMalformed(APIException):
    status_code = 400
    default_detail = "Change set nie spełnia kontraktu."
    default_code = "change_set_malformed"


class ContractVersionUnsupported(APIException):
    status_code = 422
    default_detail = "Ta wersja kontraktu nie jest obsługiwana."
    default_code = "contract_version_unsupported"


class ChangeSetTargetNotFound(APIException):
    status_code = 404
    default_detail = "Change set wskazuje zasób, który nie istnieje."
    default_code = "change_set_target_not_found"


class ChangeSetStale(APIException):
    status_code = 409
    default_detail = "Stan zmienił się od odczytu; przelicz propozycję."
    default_code = "change_set_stale"


class ChangeSetPositionInvalid(APIException):
    status_code = 422
    default_detail = "Komenda wskazuje pozycję bloku, której nie ma w wersji bazowej."
    default_code = "change_set_position_invalid"


class ChangeSetCommandUnsupported(APIException):
    status_code = 422
    default_detail = "Ta komenda nie jest wykonywana przez change set."
    default_code = "change_set_command_unsupported"


CHANGE_SET_COMMANDS = frozenset({
    "translation.update",
    "block.insert",
    "block.replace",
    "block.remove",
    "block.reorder",
})
TRANSLATION_FIELDS = ("title", "description", "social_title", "social_description")
APPROVAL_SALT = "sites.content-change-set.approval.v1"


@contextmanager
def _recorded(operation: str) -> Iterator[None]:
    """Counts how each request ended, and how long it took to decide.

    Wrapped around the whole decision rather than sprinkled at each refusal:
    a code path that forgets to count is worse than no metric, because the
    dashboard then quietly under-reports exactly the failure being introduced.
    """
    started = perf_counter()
    try:
        yield
    except APIException as refusal:
        CHANGE_SET_REFUSALS.labels(code=str(getattr(refusal, "default_code", "error"))).inc()
        CHANGE_SET_RESULTS.labels(operation=operation, outcome="refused").inc()
        raise
    except Exception:
        CHANGE_SET_RESULTS.labels(operation=operation, outcome="error").inc()
        raise
    else:
        CHANGE_SET_RESULTS.labels(operation=operation, outcome="accepted").inc()
    finally:
        CHANGE_SET_LATENCY.labels(operation=operation).observe(perf_counter() - started)


@dataclass(frozen=True, slots=True)
class ChangeSetPlan:
    """What the change set would do, without having done it."""

    target_kind: str
    resource_id: UUID
    base_version: int
    blocks: list[dict[str, Any]]
    translation_fields: dict[str, str]
    publish_at: str | None
    commands: list[str]
    binding: dict[str, Any]
    blocks_before: list[dict[str, Any]]

    @property
    def digest(self) -> str:
        """Bind this intent and caller to the exact localized effect and base."""
        return canonical_json_hash({
            "binding": self.binding,
            "target_kind": self.target_kind,
            "resource_id": str(self.resource_id),
            "base_version": self.base_version,
            "blocks": self.blocks,
            "translation_fields": self.translation_fields,
            "publish_at": self.publish_at,
        })


@cache
def change_set_validator() -> Draft202012Validator:
    directory = Path(settings.CONTENT_OPERATIONS_CONTRACTS_PATH)
    schema_path = directory / "content-change-set.v1.schema.json"
    if not schema_path.is_file():
        raise ImproperlyConfigured(f"Brak kontraktu Content Operations w {schema_path}.")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_change_set(document: Any) -> dict[str, Any]:
    """The envelope, before anything is looked up.

    Refusing a malformed document before touching the database keeps the error
    reproducible on the sender's side: they can validate the same file against
    the same schema and see exactly what we saw.
    """
    if not isinstance(document, dict):
        raise ChangeSetMalformed
    version = document.get("contract_version")
    if not isinstance(version, int):
        raise ChangeSetMalformed
    if not MINIMUM_CONTENT_CONTRACT_VERSION <= version <= CONTENT_CONTRACT_VERSION:
        # A version above ours is refused too: the sender is describing a
        # contract this build does not implement, and accepting it would mean
        # guessing what they meant.
        raise ContractVersionUnsupported(
            detail=(
                f"Obsługujemy kontrakt od {MINIMUM_CONTENT_CONTRACT_VERSION} "
                f"do {CONTENT_CONTRACT_VERSION}."
            )
        )
    errors = sorted(change_set_validator().iter_errors(document), key=lambda error: error.path)
    if errors:
        raise ChangeSetMalformed(detail="; ".join(error.message for error in errors[:3]))
    return document


def preview_change_set(document: dict[str, Any]) -> dict[str, Any]:
    """Authorizes and describes the resulting draft without writing it.

    Every position names the state at `base.version`, so the whole set is
    resolved against one list rather than applied one command at a time — the
    order the commands arrive in cannot change what "position 2" means.
    """
    with _recorded("plan"):
        context = authorize_entitled(
            SITE_CONTENT_EDIT,
            SITES_ENABLED,
            operation=FeatureOperation.READ,
        )
        plan = _plan_change_set(document, context)
        return _change_set_diff(document, plan, context)


def translation_snapshot(translation: PageTranslation) -> dict[str, Any]:
    """Immutable review evidence, including the optimistic translation version."""
    return {
        field: getattr(translation, field)
        for field in (
            *TRANSLATION_FIELDS,
            "version",
            "slug",
            "locale",
            "allow_title_fallback",
            "allow_description_fallback",
            "allow_social_title_fallback",
            "allow_social_description_fallback",
        )
    }


def read_content_base(target: dict[str, Any]) -> dict[str, Any]:
    """Return the actual target draft base; publication hashes cannot stand in for it."""
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    return _content_base(target, context)


def _content_base(target: dict[str, Any], context: TenantContext) -> dict[str, Any]:
    from .services import assert_within_grant

    target = {key: str(value) for key, value in target.items()}
    schema = dict(change_set_validator().schema)  # type: ignore[arg-type]
    target_schema = {"$ref": "#/$defs/target", "$defs": schema["$defs"]}
    if not Draft202012Validator(target_schema).is_valid(target):
        raise ChangeSetMalformed
    site = Site.all_objects.filter(
        pk=target["site_id"],
        organization_id=context.organization_id,
    ).first()
    if site is None:
        raise ChangeSetTargetNotFound
    assert_within_grant(
        context,
        site_id=site.id,
        collection_id=UUID(target["collection_id"]) if target["kind"] == "content_entry" else None,
    )
    if target["kind"] == "site_page":
        _resource, version, blocks = _page_base(target, context)
        translation = PageTranslation.all_objects.filter(
            organization_id=context.organization_id,
            page_id=target["page_id"],
            locale=target["locale"],
        ).first()
        metadata = (
            {
                field: getattr(translation, field)
                for field in (
                    *TRANSLATION_FIELDS,
                    "version",
                    "slug",
                    "allow_title_fallback",
                    "allow_description_fallback",
                    "allow_social_title_fallback",
                    "allow_social_description_fallback",
                )
            }
            if translation
            else None
        )
        fields = {field: getattr(translation, field, "") for field in TRANSLATION_FIELDS}
    else:
        _resource, version, blocks = _entry_base(target, context)
        entry = ContentEntry.all_objects.get(
            pk=target["entry_id"],
            organization_id=context.organization_id,
        )
        if entry.locale != target["locale"]:
            raise ChangeSetTargetNotFound
        metadata = {"title": entry.title, "excerpt": entry.excerpt, "locale": entry.locale}
        fields = {"title": entry.title, "excerpt": entry.excerpt}
    observed_at = timezone.now().isoformat()
    snapshot_hash = "sha256:" + canonical_json_hash({
        "target": target,
        "version": version,
        "blocks": blocks,
        "metadata": metadata,
    })
    return {
        "target": target,
        "base": {"version": version, "snapshot_hash": snapshot_hash, "observed_at": observed_at},
        "blocks": blocks,
        "translation_fields": fields,
        "observed_at": observed_at,
    }


def _plan_change_set(document: dict[str, Any], context: TenantContext) -> ChangeSetPlan:
    validate_change_set(document)
    target = document["target"]
    current = _content_base(target, context)
    base_version = current["base"]["version"]
    blocks = current["blocks"]
    resource = UUID(target["page_id"] if target["kind"] == "site_page" else target["entry_id"])
    if (
        base_version != document["base"]["version"]
        or current["base"]["snapshot_hash"] != document["base"]["snapshot_hash"]
    ):
        raise ChangeSetStale(
            detail=(
                f"Wersja bazowa {document['base']['version']} nie jest bieżąca ({base_version})."
            )
        )

    translation_fields: dict[str, str] = {}
    publish_at: str | None = None
    inserts: dict[int, dict[str, Any]] = {}
    replacements: dict[int, dict[str, Any]] = {}
    removals: set[int] = set()
    order: list[int] | None = None

    for command in document["commands"]:
        name = command["command"]
        if name not in CHANGE_SET_COMMANDS:
            raise ChangeSetCommandUnsupported(detail=f"Komenda {name} wymaga osobnej operacji.")
        if name == "translation.update":
            if target["kind"] != "site_page":
                raise ChangeSetCommandUnsupported(
                    detail="Metadane wpisu wymagają osobnej operacji."
                )
            for field, value in command["fields"].items():
                limit = getattr(PageTranslation._meta.get_field(field), "max_length", None)
                if not isinstance(limit, int) or len(value) > limit:
                    raise ChangeSetMalformed(detail=f"Pole {field} przekracza {limit} znaków.")
            translation_fields.update({
                key: value.strip() for key, value in command["fields"].items()
            })
        elif name == "block.insert":
            if command["position"] > len(blocks) or command["position"] in inserts:
                raise ChangeSetPositionInvalid
            inserts[command["position"]] = command["block"]
        elif name == "block.replace":
            _assert_position(command["position"], blocks)
            if command["position"] in replacements or command["position"] in removals:
                raise ChangeSetPositionInvalid
            replacements[command["position"]] = command["block"]
        elif name == "block.remove":
            _assert_position(command["position"], blocks)
            if command["position"] in replacements or command["position"] in removals:
                raise ChangeSetPositionInvalid
            removals.add(command["position"])
        elif name == "block.reorder":
            if order is not None or sorted(command["order"]) != list(range(len(blocks))):
                raise ChangeSetPositionInvalid
            for position in command["order"]:
                _assert_position(position, blocks)
            order = list(command["order"])
    for block in list(inserts.values()) + list(replacements.values()):
        validate_site_block(
            block_type=block["type"],
            schema_version=block["schema_version"],
            data=block["data"],
        )

    resulting = _resulting_blocks(
        blocks,
        inserts=inserts,
        replacements=replacements,
        removals=removals,
        order=order,
    )
    return ChangeSetPlan(
        target_kind=target["kind"],
        resource_id=resource,
        base_version=base_version,
        blocks=resulting,
        translation_fields=translation_fields,
        publish_at=publish_at,
        commands=[command["command"] for command in document["commands"]],
        blocks_before=blocks,
        binding={
            "organization_id": str(context.organization_id),
            "actor_id": str(context.actor_id),
            "credential_id": str(context.credential_id),
            "target": current["target"],
            "snapshot_hash": current["base"]["snapshot_hash"],
            "idempotency_key": document["idempotency_key"],
        },
    )


def _change_set_diff(
    document: dict[str, Any], plan: ChangeSetPlan, context: TenantContext
) -> dict[str, Any]:
    """What would change, computed from the same plan that would be applied.

    Derived rather than described: a diff assembled from the commands would be
    the sender's account of its own intent, which is precisely the thing an
    approval must not rest on.
    """
    return {
        "resource_id": str(plan.resource_id),
        "base_version": plan.base_version,
        "commands": plan.commands,
        "blocks_before": plan.blocks_before,
        "blocks_after": plan.blocks,
        "translation_fields": plan.translation_fields,
        "publish_at": plan.publish_at,
        "approval_digest": plan.digest,
        "approval_token": signing.dumps({"digest": plan.digest}, salt=APPROVAL_SALT),
        "digest_expires_at": (timezone.now() + settings.CONTENT_APPROVAL_DIGEST_TTL).isoformat(),
    }


def _page_base(
    target: dict[str, Any], context: TenantContext
) -> tuple[UUID, int, list[dict[str, Any]]]:
    page = (
        Page.all_objects.select_related("current_draft")
        .filter(
            pk=target["page_id"],
            organization_id=context.organization_id,
            site_id=target["site_id"],
        )
        .first()
    )
    if page is None:
        raise ChangeSetTargetNotFound
    # A page's blocks are rows, not a JSON column: `PageVersion.blocks` is the
    # reverse relation, and reading it as a list would be a manager rather than
    # the content.
    blocks = (
        [
            stored_block_payload(block)
            for block in PageBlock.all_objects.filter(
                organization_id=context.organization_id,
                page_version_id=page.current_draft.id,
            ).order_by("position")
        ]
        if page.current_draft
        else []
    )
    return page.id, page.version, blocks


def _entry_base(
    target: dict[str, Any], context: TenantContext
) -> tuple[UUID, int, list[dict[str, Any]]]:
    entry_id = target.get("entry_id")
    if entry_id is None:
        raise ChangeSetTargetNotFound
    entry = (
        ContentEntry.all_objects.select_related("current_draft")
        .filter(
            pk=entry_id,
            organization_id=context.organization_id,
            collection_id=target["collection_id"],
            collection__site_id=target["site_id"],
        )
        .first()
    )
    if entry is None:
        raise ChangeSetTargetNotFound
    blocks = list(entry.current_draft.blocks) if entry.current_draft else []
    return entry.id, entry.version, blocks


def _assert_position(position: int, blocks: list[dict[str, Any]]) -> None:
    if not 0 <= position < len(blocks):
        raise ChangeSetPositionInvalid


def _resulting_blocks(
    blocks: list[dict[str, Any]],
    *,
    inserts: dict[int, dict[str, Any]],
    replacements: dict[int, dict[str, Any]],
    removals: set[int],
    order: list[int] | None,
) -> list[dict[str, Any]]:
    kept = []
    for index in order if order is not None else range(len(blocks)):
        if index in inserts:
            kept.append(_stored(inserts[index]))
        if index not in removals:
            if index in replacements:
                replacement = _stored(replacements[index])
                # v1 connectors cannot describe decoration. Rewriting content
                # must preserve the appearance a person already chose.
                if "decoration" not in replacements[index] and "decoration" in blocks[index]:
                    replacement["decoration"] = deepcopy(blocks[index]["decoration"])
                kept.append(replacement)
            else:
                kept.append(blocks[index])
    if len(blocks) in inserts:
        kept.append(_stored(inserts[len(blocks)]))
    return kept


def _stored(block: dict[str, Any]) -> dict[str, Any]:
    """The contract's envelope, in the shape the draft services store."""
    return normalize_block({
        "block_type": block["type"],
        "schema_version": block["schema_version"],
        "data": block["data"],
        **({"decoration": block["decoration"]} if "decoration" in block else {}),
    })


class ApprovalDigestMismatch(APIException):
    status_code = 409
    default_detail = "Zatwierdzony digest nie odpowiada tej zmianie."
    default_code = "approval_digest_mismatch"


def apply_change_set(
    document: dict[str, Any],
    context: TenantContext,
    *,
    idempotency_key: str,
    approval_digest: str | None = None,
    approval_token: str | None = None,
) -> dict[str, Any]:
    """Turns an accepted change set into a new draft.

    Deliberately routed through `save_draft` and `save_entry_draft` rather than
    writing rows: the grant, the surface policy, the momentary editing lock,
    optimistic locking, audit and media references all live there, and a second
    write path would be a second place for one of them to be forgotten.
    """
    with _recorded("apply"):
        return _apply_change_set(
            document,
            context,
            idempotency_key=idempotency_key,
            approval_digest=approval_digest,
            approval_token=approval_token,
        )


@transaction.atomic
def _apply_change_set(
    document: dict[str, Any],
    context: TenantContext,
    *,
    idempotency_key: str,
    approval_digest: str | None,
    approval_token: str | None,
) -> dict[str, Any]:
    from .collections import get_entry_draft, save_entry_draft
    from .services import _is_automation, get_draft, save_draft, save_page_translation

    authorized = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    if authorized != context:
        raise ChangeSetTargetNotFound
    validate_change_set(document)
    target = document["target"]
    # The same aggregate lock is taken by editor writes, including translations.
    model = Page if target["kind"] == "site_page" else ContentEntry
    resource_id = target.get("page_id") or target.get("entry_id")
    if (
        not model.all_objects.select_for_update()
        .filter(
            pk=resource_id,
            organization_id=context.organization_id,
        )
        .exists()
    ):
        raise ChangeSetTargetNotFound
    plan = _plan_change_set(document, context)
    if approval_digest is not None and approval_digest != plan.digest:
        # The payload moved after somebody approved it, or the approval belongs
        # to a different change. Either way it is not this one.
        raise ApprovalDigestMismatch
    if approval_digest is not None or approval_token is not None:
        try:
            approval = signing.loads(
                approval_token or "",
                salt=APPROVAL_SALT,
                max_age=settings.CONTENT_APPROVAL_DIGEST_TTL,
            )
        except signing.BadSignature as error:
            raise ApprovalDigestMismatch from error
        if approval != {"digest": plan.digest}:
            raise ApprovalDigestMismatch

    metadata_before: dict[str, Any] = {}
    metadata_after: dict[str, Any] = {}
    metadata_pending = False
    if plan.target_kind == "site_page":
        draft = get_draft(page_id=plan.resource_id)
        save_draft(
            page_id=plan.resource_id,
            expected_version=plan.base_version,
            blocks=plan.blocks,
            media_asset_ids=list(draft.media_asset_ids),
            idempotency_key=idempotency_key,
            request_context={"change_set": document},
        )
        if plan.translation_fields:
            translation = PageTranslation.all_objects.filter(
                organization_id=context.organization_id,
                page_id=plan.resource_id,
                locale=target["locale"],
            ).first()
            if translation is None:
                raise ChangeSetTargetNotFound(detail="Najpierw utwórz tłumaczenie strony.")
            metadata_before = translation_snapshot(translation)
            metadata_pending = (
                _is_automation(context) and draft.page.automation_policy == "proposed"
            )
            values = {field: getattr(translation, field) for field in TRANSLATION_FIELDS}
            values.update(plan.translation_fields)
            metadata_after = {**metadata_before, **values, "version": translation.version + 1}
            if not metadata_pending:
                save_page_translation(
                    page_id=plan.resource_id,
                    locale=target["locale"],
                    expected_version=translation.version,
                    slug=translation.slug,
                    title=values["title"],
                    description=values["description"],
                    social_title=values["social_title"],
                    social_description=values["social_description"],
                    allow_title_fallback=translation.allow_title_fallback,
                    allow_description_fallback=translation.allow_description_fallback,
                    allow_social_title_fallback=translation.allow_social_title_fallback,
                    allow_social_description_fallback=translation.allow_social_description_fallback,
                    idempotency_key=idempotency_key,
                )
    else:
        entry_draft = get_entry_draft(entry_id=plan.resource_id)
        save_entry_draft(
            entry_id=plan.resource_id,
            expected_version=plan.base_version,
            blocks=plan.blocks,
            media_asset_ids=list(entry_draft.media_asset_ids),
            idempotency_key=idempotency_key,
        )
    # The reasoning outlives the request. Without it the queue can offer only
    # "an integration changed this" and a diff, which is not enough for anybody
    # to say yes or no honestly.
    rationale = document["rationale"]
    proposal, _created = ContentProposal.all_objects.update_or_create(
        organization_id=context.organization_id,
        resource_type=plan.target_kind,
        resource_id=plan.resource_id,
        version=plan.base_version + 1,
        defaults={
            "credential_id": context.credential_id,
            "summary": rationale["summary"],
            "risk": rationale["risk"],
            "expected_outcome": rationale.get("expected_outcome", ""),
            "sources": rationale["sources"],
            "commands": plan.commands,
            "target": target,
            "metadata_before": metadata_before,
            "metadata_after": metadata_after,
            "metadata_pending": metadata_pending,
        },
    )
    return {
        "resource_id": str(plan.resource_id),
        "base_version": plan.base_version,
        "applied_commands": [
            name for name in plan.commands if not metadata_pending or name != "translation.update"
        ],
        "pending_commands": ["translation.update"] if metadata_pending else [],
        "proposal_id": str(proposal.id),
        "approval_digest": plan.digest,
        # Publication stays a separate command (ADR-035 §5): accepting a change
        # is not the same act as putting it in front of readers.
        "published": False,
    }
