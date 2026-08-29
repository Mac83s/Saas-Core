"""Reading, checking and applying a ContentChangeSet (W9.6.6).

The document itself is frozen in `packages/contracts/content-operations` and
validated by both repositories against the same files. This module is the
receiving half: it decides whether a well-formed change set may take effect
here, now, on this resource, and what it would do if it did.

Nothing here mutates. `apply_change_set` calls the same domain services a
person's click calls, so an automation cannot reach a shortcut a human does not
have — which is the whole reason the commands are an allowlist rather than a
patch format.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from jsonschema import Draft202012Validator
from rest_framework.exceptions import APIException

from saas_core.modules.core.organizations.context import TenantContext

from .block_contracts import validate_site_block
from .capabilities import CONTENT_CONTRACT_VERSION, MINIMUM_CONTENT_CONTRACT_VERSION
from .models import (
    ContentCollection,
    ContentEntry,
    Page,
    PageBlock,
    PageTranslation,
    Site,
    canonical_json_hash,
)


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


class ChangeSetLinkRejected(APIException):
    status_code = 422
    default_detail = "Link prowadzi do adresu, którego ten serwis nie publikuje."
    default_code = "change_set_link_rejected"


class ChangeSetPositionInvalid(APIException):
    status_code = 422
    default_detail = "Komenda wskazuje pozycję bloku, której nie ma w wersji bazowej."
    default_code = "change_set_position_invalid"


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

    @property
    def digest(self) -> str:
        """Binds an approval to this exact effect.

        Not to the request: two different requests that produce the same draft
        deserve the same approval, and a payload edited after approval must not
        inherit it.
        """
        return canonical_json_hash({
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
        raise ImproperlyConfigured(
            f"Brak kontraktu Content Operations w {schema_path}."
        )
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
    errors = sorted(
        change_set_validator().iter_errors(document), key=lambda error: error.path
    )
    if errors:
        raise ChangeSetMalformed(
            detail="; ".join(error.message for error in errors[:3])
        )
    return document


def plan_change_set(document: dict[str, Any], context: TenantContext) -> ChangeSetPlan:
    """Works out the resulting draft without writing it.

    Every position names the state at `base.version`, so the whole set is
    resolved against one list rather than applied one command at a time — the
    order the commands arrive in cannot change what "position 2" means.
    """
    validate_change_set(document)
    target = document["target"]
    site = Site.all_objects.filter(
        pk=target["site_id"], organization_id=context.organization_id
    ).first()
    if site is None:
        raise ChangeSetTargetNotFound

    if target["kind"] == "site_page":
        resource, base_version, blocks = _page_base(target, context)
    else:
        resource, base_version, blocks = _entry_base(target, context)
    if base_version != document["base"]["version"]:
        raise ChangeSetStale(
            detail=(
                f"Wersja bazowa {document['base']['version']} nie jest bieżąca "
                f"({base_version})."
            )
        )

    translation_fields: dict[str, str] = {}
    publish_at: str | None = None
    inserts: dict[int, dict[str, Any]] = {}
    replacements: dict[int, dict[str, Any]] = {}
    removals: set[int] = set()
    order: list[int] | None = None
    links: list[dict[str, Any]] = []

    for command in document["commands"]:
        name = command["command"]
        if name == "translation.update":
            translation_fields.update(command["fields"])
        elif name == "publication.schedule":
            publish_at = command["publish_at"]
        elif name == "block.insert":
            inserts[command["position"]] = command["block"]
        elif name == "block.replace":
            _assert_position(command["position"], blocks)
            replacements[command["position"]] = command["block"]
        elif name == "block.remove":
            _assert_position(command["position"], blocks)
            removals.add(command["position"])
        elif name == "block.reorder":
            for position in command["order"]:
                _assert_position(position, blocks)
            order = list(command["order"])
        elif name == "internal_link.add":
            _assert_position(command["position"], blocks)
            links.append(command)
        # `page.create` and `entry.create` are answered by the create endpoints
        # rather than here: a change set targets a resource that exists, and a
        # creation has no base version to be stale against.

    for block in list(inserts.values()) + list(replacements.values()):
        validate_site_block(
            block_type=block["type"],
            schema_version=block["schema_version"],
            data=block["data"],
        )
    for link in links:
        _assert_link_resolves(link["target_path"], site=site, context=context)

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
    )


def change_set_diff(
    document: dict[str, Any], plan: ChangeSetPlan, context: TenantContext
) -> dict[str, Any]:
    """What would change, computed from the same plan that would be applied.

    Derived rather than described: a diff assembled from the commands would be
    the sender's account of its own intent, which is precisely the thing an
    approval must not rest on.
    """
    if plan.target_kind == "site_page":
        _resource, _version, before = _page_base(document["target"], context)
    else:
        _resource, _version, before = _entry_base(document["target"], context)
    return {
        "resource_id": str(plan.resource_id),
        "base_version": plan.base_version,
        "commands": plan.commands,
        "blocks_before": before,
        "blocks_after": plan.blocks,
        "translation_fields": plan.translation_fields,
        "publish_at": plan.publish_at,
        "approval_digest": plan.digest,
        "digest_expires_at": (
            timezone.now() + settings.CONTENT_APPROVAL_DIGEST_TTL
        ).isoformat(),
    }


def _page_base(
    target: dict[str, Any], context: TenantContext
) -> tuple[UUID, int, list[dict[str, Any]]]:
    page = Page.all_objects.select_related("current_draft").filter(
        pk=target["page_id"],
        organization_id=context.organization_id,
        site_id=target["site_id"],
    ).first()
    if page is None:
        raise ChangeSetTargetNotFound
    # A page's blocks are rows, not a JSON column: `PageVersion.blocks` is the
    # reverse relation, and reading it as a list would be a manager rather than
    # the content.
    blocks = (
        [
            {
                "block_type": block.block_type,
                "schema_version": block.schema_version,
                "data": block.data,
            }
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
    entry = ContentEntry.all_objects.select_related("current_draft").filter(
        pk=entry_id,
        organization_id=context.organization_id,
        collection_id=target["collection_id"],
    ).first()
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
    kept = [
        _stored(replacements[index]) if index in replacements else block
        for index, block in enumerate(blocks)
        if index not in removals
    ]
    if order is not None:
        surviving = [index for index in order if index not in removals]
        kept = [
            _stored(replacements[index]) if index in replacements else blocks[index]
            for index in surviving
        ]
    for position in sorted(inserts):
        kept.insert(min(position, len(kept)), _stored(inserts[position]))
    return kept


def _stored(block: dict[str, Any]) -> dict[str, Any]:
    """The contract's envelope, in the shape the draft services store."""
    return {
        "block_type": block["type"],
        "schema_version": block["schema_version"],
        "data": block["data"],
    }


def _assert_link_resolves(path: str, *, site: Site, context: TenantContext) -> None:
    """An internal link points at something this site actually publishes.

    A link to a page that does not exist yet is refused rather than written as
    a promise: a broken link on a customer's site is worse than a missing one,
    and nothing later goes back to check.
    """
    wanted = path.rstrip("/") or "/"
    slugs = {
        f"/{slug}".rstrip("/") or "/"
        for slug in PageTranslation.all_objects.filter(
            organization_id=context.organization_id, site_id=site.id
        ).values_list("slug", flat=True)
    }
    if wanted in slugs:
        return
    for collection in ContentCollection.all_objects.filter(
        organization_id=context.organization_id, site_id=site.id
    ):
        if wanted == f"/{collection.base_path}":
            return
        if wanted.startswith(f"/{collection.base_path}/"):
            slug = wanted.rsplit("/", 1)[-1]
            if ContentEntry.all_objects.filter(
                organization_id=context.organization_id,
                collection_id=collection.id,
                slug=slug,
            ).exists():
                return
    raise ChangeSetLinkRejected(detail=f"Adres {path} nie istnieje w tym serwisie.")


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
) -> dict[str, Any]:
    """Turns an accepted change set into a new draft.

    Deliberately routed through `save_draft` and `save_entry_draft` rather than
    writing rows: the grant, the surface policy, the momentary editing lock,
    optimistic locking, audit and media references all live there, and a second
    write path would be a second place for one of them to be forgotten.
    """
    from .collections import save_entry_draft
    from .services import save_draft

    plan = plan_change_set(document, context)
    if approval_digest is not None and approval_digest != plan.digest:
        # The payload moved after somebody approved it, or the approval belongs
        # to a different change. Either way it is not this one.
        raise ApprovalDigestMismatch

    if plan.target_kind == "site_page":
        save_draft(
            page_id=plan.resource_id,
            expected_version=plan.base_version,
            blocks=plan.blocks,
            media_asset_ids=[],
            idempotency_key=idempotency_key,
        )
    else:
        save_entry_draft(
            entry_id=plan.resource_id,
            expected_version=plan.base_version,
            blocks=plan.blocks,
            idempotency_key=idempotency_key,
        )
    return {
        "resource_id": str(plan.resource_id),
        "base_version": plan.base_version,
        "applied_commands": plan.commands,
        "approval_digest": plan.digest,
        # Publication stays a separate command (ADR-035 §5): accepting a change
        # is not the same act as putting it in front of readers.
        "published": False,
    }
