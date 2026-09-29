"""An organization's own templates (F4-B; owner's answers 1a–4a, 2026-09-28).

A person with the right to edit the site saves a section or a whole page — its
content and photos, exactly as a draft stores them — as a template for the
whole organization. Editing a template saves its next immutable version; pages
built from it are copies and never change with it. System recipes stay files
(`page_templates.py`); these rows are tenant data under forced RLS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.api import (
    ResourceReferenceConflict,
    ResourceReferenceRejected,
    record_resource_references,
)
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import (
    FeatureOperation,
    authorize_entitled,
    decide_quota,
)

from .block_contracts import validate_site_block
from .block_decoration import normalize_block, validate_page_presentation
from .models import (
    Page,
    PageVersion,
    SiteTemplate,
    SiteTemplateKind,
    SiteTemplateVersion,
    canonical_json_hash,
)
from .permissions import SITE_CONTENT_EDIT, SITE_TEMPLATES_MAX, SITES_ENABLED
from .real_media import assert_real_media_slots
from .rich_content import assert_unique_anchors, block_asset_ids
from .services import (
    MEDIA_ASSET_RESOURCE_TYPE,
    MutationResult,
    PageNotFound,
    SiteMediaReferenceUnavailable,
    SitesIdempotencyConflict,
    _idempotency_key,
    _placed,
    assert_person_required,
    save_draft,
    swap_into_template,
)

TEMPLATE_VERSION_REFERENCE_OWNER = "sites.template_version"
SITE_TEMPLATE_CREATED = "sites.template.created"
SITE_TEMPLATE_VERSION_SAVED = "sites.template.version_saved"
SITE_TEMPLATE_UPDATED = "sites.template.updated"
SITE_TEMPLATE_ARCHIVED = "sites.template.archived"
OWN_TEMPLATE_IMPORTED = "sites.page.own_template_imported"
VERSION_ORIGIN_OWN_TEMPLATE = "own_template"
#: A page template holds what a page may: the recipe limit (page-template v3+).
MAX_PAGE_TEMPLATE_BLOCKS = 20


class SiteTemplateNotFound(NotFound):
    default_detail = "Szablon nie istnieje."
    default_code = "site_template_not_found"


class SiteTemplateVersionConflict(APIException):
    status_code = 409
    default_detail = "Szablon zmienił się w międzyczasie. Odśwież listę szablonów."
    default_code = "site_template_version_conflict"


class SiteTemplateNameTaken(APIException):
    status_code = 409
    default_detail = "Szablon o tej nazwie już istnieje. Wybierz inną nazwę."
    default_code = "site_template_name_taken"


class SiteTemplateLimitReached(APIException):
    status_code = 403
    default_code = "site_template_limit_reached"

    def __init__(self, limit: int) -> None:
        super().__init__(
            detail=(
                f"Plan pozwala na {limit} szablonów firmy. Zarchiwizuj szablon "
                "albo wybierz wyższy plan, żeby zapisać kolejny."
            ),
            code=self.default_code,
        )


class SiteTemplateInvalid(APIException):
    status_code = 400
    default_code = "site_template_invalid"


@dataclass(frozen=True, slots=True)
class OwnTemplate:
    template: SiteTemplate
    version: SiteTemplateVersion


def _normalized_content(
    *,
    kind: str,
    blocks: list[dict[str, Any]],
    page_presentation: dict[str, Any] | None,
    organization_id: UUID,
) -> list[dict[str, Any]]:
    """The checks a draft save runs, and the shape a kind allows."""
    normalized = [normalize_block(block) for block in blocks]
    if kind == SiteTemplateKind.SECTION and len(normalized) != 1:
        raise SiteTemplateInvalid(detail="Szablon sekcji zawiera dokładnie jedną sekcję.")
    if kind == SiteTemplateKind.PAGE and not 1 <= len(normalized) <= MAX_PAGE_TEMPLATE_BLOCKS:
        raise SiteTemplateInvalid(
            detail=f"Szablon strony ma od 1 do {MAX_PAGE_TEMPLATE_BLOCKS} sekcji."
        )
    if kind == SiteTemplateKind.SECTION and page_presentation is not None:
        raise SiteTemplateInvalid(detail="Szablon sekcji nie niesie wyglądu strony.")
    for block in normalized:
        validate_site_block(
            block_type=block["block_type"],
            schema_version=block["schema_version"],
            data=block["data"],
        )
    assert_unique_anchors(normalized)
    assert_real_media_slots(organization_id=organization_id, blocks=normalized)
    validate_page_presentation(page_presentation)
    return normalized


def _media(normalized: list[dict[str, Any]], listed: list[UUID]) -> list[str]:
    # Photos nested in block data count even when the client did not list them.
    return sorted({
        *(str(item) for item in listed),
        *(str(item) for item in block_asset_ids(normalized)),
    })


def _reference_media(context: Any, version: SiteTemplateVersion) -> None:
    try:
        record_resource_references(
            context=context,
            resource_type=MEDIA_ASSET_RESOURCE_TYPE,
            owner_type=TEMPLATE_VERSION_REFERENCE_OWNER,
            owner_id=version.id,
            resource_ids=tuple(UUID(item) for item in version.media_asset_ids),
        )
    except ResourceReferenceRejected as error:
        raise SiteMediaReferenceUnavailable from error
    except ResourceReferenceConflict as error:
        raise SitesIdempotencyConflict from error


def _audit(context: Any, action: str, template: SiteTemplate, **metadata: Any) -> None:
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=action,
        actor=User.objects.get(pk=context.actor_id),
        target_type="site_template",
        target_id=template.id,
        metadata={"kind": template.kind, "name": template.name, **metadata},
    )


def _locked_template(context: Any, template_id: UUID) -> SiteTemplate:
    template = (
        SiteTemplate.all_objects.select_for_update()
        .filter(pk=template_id, organization_id=context.organization_id, archived_at__isnull=True)
        .first()
    )
    if template is None:
        raise SiteTemplateNotFound
    return template


def list_site_templates(*, kind: str | None = None) -> tuple[list[OwnTemplate], int | None]:
    """The organization's active templates with their newest version, and the
    plan's limit (None: no limit)."""
    context = authorize_entitled(
        SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ
    )
    templates = SiteTemplate.all_objects.filter(
        organization_id=context.organization_id, archived_at__isnull=True
    ).select_related("created_by")
    if kind:
        templates = templates.filter(kind=kind)
    rows = list(templates.order_by("kind", "name"))
    versions = {
        (version.template_id, version.number): version
        for version in SiteTemplateVersion.all_objects.filter(
            organization_id=context.organization_id,
            template_id__in=[template.id for template in rows],
        ).select_related("created_by")
    }
    decision = decide_quota(SITE_TEMPLATES_MAX)
    return (
        [
            OwnTemplate(template, versions[(template.id, template.current_version)])
            for template in rows
            if (template.id, template.current_version) in versions
        ],
        decision.value if decision.available else None,
    )


@transaction.atomic
def create_site_template(
    *,
    kind: str,
    name: str,
    description: str,
    blocks: list[dict[str, Any]],
    page_presentation: dict[str, Any] | None,
    media_asset_ids: list[UUID],
    source_page_id: UUID | None,
    idempotency_key: str,
) -> MutationResult[OwnTemplate]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, "Szablon firmy")
    key = _idempotency_key(idempotency_key)
    normalized = _normalized_content(
        kind=kind,
        blocks=blocks,
        page_presentation=page_presentation,
        organization_id=context.organization_id,
    )
    media = _media(normalized, media_asset_ids)
    request_hash = canonical_json_hash({
        "kind": kind,
        "name": name.strip(),
        "description": description.strip(),
        "blocks": normalized,
        "page_presentation": page_presentation,
        "media_asset_ids": media,
    })
    existing = SiteTemplate.all_objects.filter(
        organization_id=context.organization_id,
        created_by_id=context.actor_id,
        idempotency_key=key,
    ).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise SitesIdempotencyConflict
        version = SiteTemplateVersion.all_objects.get(template=existing, number=1)
        return MutationResult(OwnTemplate(existing, version), False)
    decision = decide_quota(SITE_TEMPLATES_MAX)
    if decision.available:
        active = SiteTemplate.all_objects.filter(
            organization_id=context.organization_id, archived_at__isnull=True
        ).count()
        if active >= decision.value:
            raise SiteTemplateLimitReached(decision.value)
    actor = User.objects.get(pk=context.actor_id)
    try:
        with transaction.atomic():
            template = SiteTemplate.all_objects.create(
                organization_id=context.organization_id,
                kind=kind,
                name=name.strip(),
                description=description.strip(),
                current_version=1,
                created_by=actor,
                idempotency_key=key,
                request_hash=request_hash,
            )
    except IntegrityError as error:
        raise SiteTemplateNameTaken from error
    version = SiteTemplateVersion.all_objects.create(
        organization_id=context.organization_id,
        template=template,
        number=1,
        blocks=normalized,
        page_presentation=page_presentation,
        media_asset_ids=media,
        content_hash=canonical_json_hash({
            "blocks": normalized,
            "page_presentation": page_presentation,
        }),
        source_page_id=source_page_id,
        created_by=actor,
        idempotency_key=key,
        request_hash=request_hash,
    )
    _reference_media(context, version)
    _audit(context, SITE_TEMPLATE_CREATED, template, version=1, block_count=len(normalized))
    return MutationResult(OwnTemplate(template, version), True)


@transaction.atomic
def save_site_template_version(
    *,
    template_id: UUID,
    expected_version: int,
    blocks: list[dict[str, Any]],
    page_presentation: dict[str, Any] | None,
    media_asset_ids: list[UUID],
    source_page_id: UUID | None,
    idempotency_key: str,
) -> MutationResult[OwnTemplate]:
    """The template's next version; earlier ones and pages built from them stay."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, "Szablon firmy")
    key = _idempotency_key(idempotency_key)
    template = _locked_template(context, template_id)
    normalized = _normalized_content(
        kind=template.kind,
        blocks=blocks,
        page_presentation=page_presentation,
        organization_id=context.organization_id,
    )
    media = _media(normalized, media_asset_ids)
    request_hash = canonical_json_hash({
        "template_id": str(template.id),
        "expected_version": expected_version,
        "blocks": normalized,
        "page_presentation": page_presentation,
        "media_asset_ids": media,
    })
    existing = SiteTemplateVersion.all_objects.filter(
        organization_id=context.organization_id,
        template=template,
        created_by_id=context.actor_id,
        idempotency_key=key,
    ).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise SitesIdempotencyConflict
        return MutationResult(OwnTemplate(template, existing), False)
    if template.current_version != expected_version:
        raise SiteTemplateVersionConflict
    actor = User.objects.get(pk=context.actor_id)
    version = SiteTemplateVersion.all_objects.create(
        organization_id=context.organization_id,
        template=template,
        number=expected_version + 1,
        blocks=normalized,
        page_presentation=page_presentation,
        media_asset_ids=media,
        content_hash=canonical_json_hash({
            "blocks": normalized,
            "page_presentation": page_presentation,
        }),
        source_page_id=source_page_id,
        created_by=actor,
        idempotency_key=key,
        request_hash=request_hash,
    )
    template.current_version = version.number
    template.save(update_fields=["current_version", "updated_at"])
    _reference_media(context, version)
    _audit(
        context,
        SITE_TEMPLATE_VERSION_SAVED,
        template,
        version=version.number,
        block_count=len(normalized),
    )
    return MutationResult(OwnTemplate(template, version), True)


@transaction.atomic
def update_site_template(*, template_id: UUID, name: str, description: str) -> OwnTemplate:
    """Renames or re-describes a template; its versions stay as they were."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, "Szablon firmy")
    template = _locked_template(context, template_id)
    template.name = name.strip()
    template.description = description.strip()
    try:
        with transaction.atomic():
            template.save(update_fields=["name", "description", "updated_at"])
    except IntegrityError as error:
        raise SiteTemplateNameTaken from error
    _audit(context, SITE_TEMPLATE_UPDATED, template)
    version = SiteTemplateVersion.all_objects.get(
        organization_id=context.organization_id,
        template=template,
        number=template.current_version,
    )
    return OwnTemplate(template, version)


@transaction.atomic
def archive_site_template(*, template_id: UUID) -> None:
    """Takes a template out of the library. Its versions and photos stay, as
    do the pages built from it; archiving frees a place in the plan's limit."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, "Szablon firmy")
    template = _locked_template(context, template_id)
    template.archived_at = timezone.now()
    template.save(update_fields=["archived_at", "updated_at"])
    _audit(context, SITE_TEMPLATE_ARCHIVED, template)


@transaction.atomic
def import_own_page_template(
    *,
    page_id: UUID,
    template_id: UUID,
    template_version: int,
    expected_version: int,
    idempotency_key: str,
    kept: list[dict[str, Any]] | None = None,
    appended: list[dict[str, Any]] | None = None,
) -> MutationResult[PageVersion]:
    """A page template of the organization becomes the page's next draft
    version, through the same `save_draft` as every other change. `kept` and
    `appended` work as for a ready template (F4-C)."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    if not Page.all_objects.filter(pk=page_id, organization_id=context.organization_id).exists():
        raise PageNotFound
    version = (
        SiteTemplateVersion.all_objects.select_related("template")
        .filter(
            organization_id=context.organization_id,
            template_id=template_id,
            number=template_version,
            template__kind=SiteTemplateKind.PAGE,
        )
        .first()
    )
    if version is None:
        raise SiteTemplateNotFound
    blocks = [dict(block) for block in version.blocks]
    taken = swap_into_template(blocks, kept)
    # A photo only a replaced section showed is not the page's any more.
    left = set(block_asset_ids(block for slot, block in enumerate(blocks) if slot not in taken))
    gone = set(block_asset_ids(blocks[slot] for slot in taken)) - left
    request_context: dict[str, Any] = {"own_template": f"{template_id}@{template_version}"}
    if kept:
        request_context["kept"] = sorted(taken)
    if appended:
        request_context["appended"] = len(appended)
    result = save_draft(
        page_id=page_id,
        expected_version=expected_version,
        blocks=_placed(blocks, kept, appended),
        media_asset_ids=[UUID(item) for item in version.media_asset_ids if UUID(item) not in gone],
        idempotency_key=idempotency_key,
        request_context=request_context,
        page_presentation=version.page_presentation,
        origin=VERSION_ORIGIN_OWN_TEMPLATE,
        origin_ref=f"{version.template.name}@{template_version}",
    )
    if result.created:
        _audit(
            context,
            OWN_TEMPLATE_IMPORTED,
            version.template,
            page_id=str(page_id),
            version=template_version,
            **({"kept_sections": len(taken)} if kept else {}),
            **({"appended_sections": len(appended)} if appended else {}),
        )
    return result
