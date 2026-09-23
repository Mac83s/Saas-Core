"""A generator fills approved text slots; Core remains the author of the structure."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from django.db import transaction
from rest_framework.exceptions import APIException

from saas_core.modules.core.identity.models import User
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .block_contracts import site_block_contracts
from .models import (
    BlueprintImportReceipt,
    ContentProposal,
    PageAutomationPolicy,
    PageTranslation,
    Site,
)
from .page_templates import PageTemplate, page_template_catalog
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED
from .services import (
    SiteNotFound,
    _idempotency_key,
    assert_within_grant,
    create_page,
    import_page_template,
)

TEXT_FIELDS = frozenset({
    "title", "text", "question", "answer", "label", "subtitle", "lead", "tagline", "eyebrow",
})
SLOT_MAX_LENGTH = {"text": 2000, "answer": 2000, "lead": 1200, "eyebrow": 80}


class BlueprintRefused(APIException):
    status_code = 422
    default_code = "blueprint_refused"
    default_detail = "Wynik generacji nie odpowiada zatwierdzonemu szablonowi."


class BlueprintConflict(APIException):
    status_code = 409
    default_code = "blueprint_conflict"
    default_detail = "Katalog lub dane tego zamiaru zmieniły się."


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _site(
    site_id: UUID, *, writing: bool = False, payload_bytes: int | None = None
) -> tuple[Any, Site]:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.WRITE if writing else FeatureOperation.READ,
    )
    query = Site.all_objects.filter(pk=site_id, organization_id=context.organization_id)
    if writing:
        query = query.select_for_update()
    site = query.first()
    if site is None:
        raise SiteNotFound
    assert_within_grant(context, site_id=site.id, writing=writing, payload_bytes=payload_bytes)
    return context, site


def _schema_node(schema: dict[str, Any], node: Any, value: Any) -> Any:
    """The schema node that governs `value`: `$ref` resolved within the block's
    own schema, a `oneOf` of node shapes narrowed by the node's `type`."""
    while isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            node = schema.get("$defs", {}).get(ref.removeprefix("#/$defs/"))
            continue
        branches = node.get("oneOf")
        if isinstance(branches, list) and isinstance(value, dict):
            node = next(
                (
                    branch
                    for branch in (_schema_node(schema, b, None) for b in branches)
                    if isinstance(branch, dict)
                    and branch.get("properties", {}).get("type", {}).get("const")
                    == value.get("type")
                ),
                None,
            )
            continue
        return node
    return None


def template_slots(template: PageTemplate) -> list[dict[str, Any]]:
    """Every plain-text slot a generator may fill, capped by the block schema's
    own limit at that path (a hero title 120, a button label 80), so a value
    that fits the slot always fits the block."""
    contracts = site_block_contracts().validators
    slots: list[dict[str, Any]] = []

    def visit(value: Any, path: str, schema: dict[str, Any], node: Any, field: str = "") -> None:
        node = _schema_node(schema, node, value)
        if isinstance(value, dict):
            # Quotes are attributed statements: automation must not put words
            # in anyone's mouth, neither in a quote block nor a quote node.
            if value.get("type") == "quote":
                return
            properties = node.get("properties", {}) if isinstance(node, dict) else {}
            for key, child in value.items():
                visit(child, path + "/" + key, schema, properties.get(key), key)
        elif isinstance(value, list):
            items = node.get("items") if isinstance(node, dict) else None
            for index, child in enumerate(value):
                visit(child, path + "/" + str(index), schema, items)
        # A run of spaces between two marked runs can never be refilled
        # (render_slots refuses blank values), so it is not offered at all.
        elif isinstance(value, str) and field in TEXT_FIELDS and value.strip():
            cap = SLOT_MAX_LENGTH.get(field, 200)
            schema_cap = node.get("maxLength") if isinstance(node, dict) else None
            slots.append({
                "key": path,
                "kind": "text",
                "max_length": min(cap, schema_cap) if isinstance(schema_cap, int) else cap,
                "default": value,
            })

    for index, block in enumerate(template.blocks):
        if block["block_type"] in {"core.pricing", "core.legal", "core.quote"}:
            continue
        validator = contracts.get(block["block_type"], {}).get(block["schema_version"])
        raw = validator.schema if validator is not None else None
        schema: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
        visit(block["data"], f"/{index}/data", schema, schema)
    return slots


def read_blueprint_catalog(*, site_id: UUID) -> dict[str, Any]:
    _site(site_id)
    templates = []
    for versions in page_template_catalog().templates.values():
        template = versions[max(versions)]
        if template.retired:
            continue
        try:
            for entitlement in template.required_entitlements:
                authorize_entitled(SITE_CONTENT_EDIT, entitlement, operation=FeatureOperation.READ)
        except APIException:
            continue
        templates.append({
            "id": template.id,
            "version": template.version,
            "labels": {locale: value["name"] for locale, value in template.labels.items()},
            "slots": template_slots(template),
        })
    result = {"contract_version": 1, "site_id": str(site_id), "templates": templates}
    return {**result, "catalog_hash": canonical_hash(result)}


def render_slots(template: PageTemplate, values: dict[str, str]) -> list[dict[str, Any]]:
    definitions = {item["key"]: item for item in template_slots(template)}
    if not isinstance(values, dict) or set(values) != set(definitions):
        raise BlueprintRefused
    blocks = template.draft_blocks()
    for key, value in values.items():
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > definitions[key]["max_length"]
            or "<" in value
            or ">" in value
        ):
            raise BlueprintRefused
        parts = key.removeprefix("/").split("/")
        current: Any = blocks
        for part in parts[:-1]:
            current = current[int(part)] if isinstance(current, list) else current[part]
        current[parts[-1]] = value
    return blocks


def _receipt_query(context: Any, site_id: UUID, key: str) -> Any:
    return BlueprintImportReceipt.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site_id,
        created_by_id=context.actor_id,
        credential_id=context.credential_id,
        idempotency_key=key,
    )


def read_blueprint_receipt(*, site_id: UUID, idempotency_key: str) -> dict[str, Any]:
    context, _ = _site(site_id)
    row = _receipt_query(context, site_id, _idempotency_key(idempotency_key)).first()
    return {"found": row is not None, "result": row.result if row else None}


@transaction.atomic
def import_blueprint(*, site_id: UUID, document: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    context, site = _site(site_id, writing=True, payload_bytes=len(json.dumps(document).encode()))
    key = _idempotency_key(document["idempotency_key"])
    request_hash = canonical_hash(document)
    prior = _receipt_query(context, site_id, key).first()
    if prior:
        if prior.request_hash != request_hash:
            raise BlueprintConflict
        return prior.result, False
    catalog = read_blueprint_catalog(site_id=site_id)
    if document["catalog_hash"] != catalog["catalog_hash"] or not any(
        item["id"] == document["template_id"] and item["version"] == document["template_version"]
        for item in catalog["templates"]
    ):
        raise BlueprintConflict
    template = page_template_catalog().get(
        template_id=document["template_id"], version=document["template_version"]
    )
    render_slots(template, document["slots"])
    if PageTranslation.all_objects.filter(
        organization_id=context.organization_id,
        site=site,
        locale=document["locale"],
        slug=document["key"],
    ).exists():
        raise BlueprintConflict
    page = create_page(
        site_id=site_id,
        name=document["name"],
        key=document["key"],
        idempotency_key="blueprint-page-" + request_hash,
    ).value
    if page.version or page.current_draft_id:
        raise BlueprintConflict
    page.automation_policy = PageAutomationPolicy.PROPOSED
    page.save(update_fields=["automation_policy"])
    version = import_page_template(
        page_id=page.id,
        template_id=template.id,
        template_version=template.version,
        expected_version=0,
        idempotency_key=key,
        text_values=document["slots"],
    ).value
    translation = PageTranslation.all_objects.create(
        organization_id=context.organization_id,
        site=site,
        page=page,
        locale=document["locale"],
        slug=document["key"],
        title=document["name"],
    )
    from .change_sets import translation_snapshot

    metadata = translation_snapshot(translation)
    proposal = ContentProposal.all_objects.create(
        organization_id=context.organization_id,
        resource_type="site_page",
        resource_id=page.id,
        version=version.number,
        credential_id=context.credential_id,
        summary=(
            "Strona z briefu: sprawdź treść, przykładowe dane kontaktowe "
            "i odnośniki przed publikacją."
        ),
        risk="medium",
        sources=[
            {
                "kind": "editorial",
                "reference": "scr:brief:" + document["generation_id"],
                "observed_at": version.created_at.isoformat(),
            }
        ],
        commands=["page.create", "template.text.fill"],
        target={
            "kind": "site_page",
            "site_id": str(site.id),
            "page_id": str(page.id),
            "locale": document["locale"],
        },
        metadata_before=metadata,
        metadata_after={**metadata, "version": metadata["version"] + 1},
        metadata_pending=True,
    )
    result = {
        "generation_id": document["generation_id"],
        "site_id": str(site.id),
        "page_id": str(page.id),
        "proposal_id": str(proposal.id),
        "draft_version": version.number,
        "request_hash": request_hash,
        "published": False,
    }
    BlueprintImportReceipt.all_objects.create(
        organization_id=context.organization_id,
        site=site,
        page=page,
        proposal=proposal,
        created_by=User.objects.get(pk=context.actor_id),
        credential_id=context.credential_id,
        idempotency_key=key,
        request_hash=request_hash,
        result=result,
    )
    return result, True
