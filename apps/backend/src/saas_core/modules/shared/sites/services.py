from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import (
    FeatureOperation,
    authorize_entitled,
    consume_quota,
)

from .models import Page, PageBlock, PageVersion, Site, canonical_json_hash
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED, SITES_MAX

SITE_CREATED = "sites.site.created"
PAGE_CREATED = "sites.page.created"
PAGE_DRAFT_SAVED = "sites.page.draft_saved"


class SitesIdempotencyConflict(APIException):
    status_code = 409
    default_detail = "Klucz idempotencji wskazuje inne żądanie."
    default_code = "sites_idempotency_conflict"


class SiteSlugConflict(APIException):
    status_code = 409
    default_detail = "Slug strony jest już używany w tej organizacji."
    default_code = "site_slug_conflict"


class PageKeyConflict(APIException):
    status_code = 409
    default_detail = "Klucz podstrony jest już używany w tej stronie."
    default_code = "page_key_conflict"


class DraftVersionConflict(APIException):
    status_code = 409
    default_detail = "Draft został w międzyczasie zmieniony."
    default_code = "draft_version_conflict"


class SiteNotFound(NotFound):
    default_detail = "Strona nie istnieje."
    default_code = "site_not_found"


class PageNotFound(NotFound):
    default_detail = "Podstrona nie istnieje."
    default_code = "page_not_found"


@dataclass(frozen=True, slots=True)
class MutationResult[T]:
    value: T
    created: bool


@dataclass(frozen=True, slots=True)
class PageDraft:
    page: Page
    version: PageVersion | None
    blocks: tuple[PageBlock, ...]


def list_sites(*, cursor: UUID | None, limit: int) -> tuple[list[Site], UUID | None]:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    queryset = Site.all_objects.filter(organization_id=context.organization_id).order_by("id")
    if cursor is not None:
        queryset = queryset.filter(id__gt=cursor)
    rows = list(queryset[: limit + 1])
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return rows[:limit], next_cursor


@transaction.atomic
def create_site(
    *,
    name: str,
    slug: str,
    default_locale: str,
    idempotency_key: str,
) -> MutationResult[Site]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    normalized_slug = slug.strip().lower()
    request_hash = canonical_json_hash(
        {
            "name": name,
            "slug": normalized_slug,
            "default_locale": default_locale,
        }
    )
    existing = Site.all_objects.filter(
        organization_id=context.organization_id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        return MutationResult(_same_request(existing, request_hash), False)

    consume_quota(
        SITES_MAX,
        amount=1,
        idempotency_key=_quota_idempotency_key(context.actor_id, normalized_key),
    )
    existing = Site.all_objects.filter(
        organization_id=context.organization_id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        return MutationResult(_same_request(existing, request_hash), False)
    if Site.all_objects.filter(
        organization_id=context.organization_id,
        slug=normalized_slug,
    ).exists():
        raise SiteSlugConflict

    organization = Organization.objects.get(pk=context.organization_id)
    actor = User.objects.get(pk=context.actor_id)
    site = Site.all_objects.create(
        organization=organization,
        name=name,
        slug=normalized_slug,
        default_locale=default_locale,
        created_by=actor,
        idempotency_key=normalized_key,
        request_hash=request_hash,
    )
    record_audit(
        organization=organization,
        action=SITE_CREATED,
        actor=actor,
        target_type="site",
        target_id=site.id,
        metadata={"slug": site.slug, "default_locale": site.default_locale},
    )
    return MutationResult(site, True)


def list_pages(
    *,
    site_id: UUID,
    cursor: UUID | None,
    limit: int,
) -> tuple[list[Page], UUID | None]:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    if not Site.all_objects.filter(
        pk=site_id,
        organization_id=context.organization_id,
    ).exists():
        raise SiteNotFound
    queryset = (
        Page.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site_id,
        )
        .select_related("current_draft")
        .order_by("id")
    )
    if cursor is not None:
        queryset = queryset.filter(id__gt=cursor)
    rows = list(queryset[: limit + 1])
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return rows[:limit], next_cursor


@transaction.atomic
def create_page(
    *,
    site_id: UUID,
    name: str,
    key: str,
    idempotency_key: str,
) -> MutationResult[Page]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    normalized_idempotency_key = _idempotency_key(idempotency_key)
    normalized_page_key = key.strip().lower()
    request_hash = canonical_json_hash(
        {"site_id": str(site_id), "name": name, "key": normalized_page_key}
    )
    try:
        site = Site.all_objects.select_for_update().get(
            pk=site_id,
            organization_id=context.organization_id,
        )
    except Site.DoesNotExist as error:
        raise SiteNotFound from error
    existing = Page.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site.id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_idempotency_key,
    ).first()
    if existing is not None:
        return MutationResult(_same_request(existing, request_hash), False)
    if Page.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site.id,
        key=normalized_page_key,
    ).exists():
        raise PageKeyConflict

    actor = User.objects.get(pk=context.actor_id)
    page = Page.all_objects.create(
        organization_id=context.organization_id,
        site=site,
        name=name,
        key=normalized_page_key,
        created_by=actor,
        idempotency_key=normalized_idempotency_key,
        request_hash=request_hash,
    )
    record_audit(
        organization=site.organization,
        action=PAGE_CREATED,
        actor=actor,
        target_type="page",
        target_id=page.id,
        metadata={"site_id": str(site.id), "key": page.key},
    )
    return MutationResult(page, True)


def get_draft(*, page_id: UUID) -> PageDraft:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    try:
        page = Page.all_objects.select_related("current_draft").get(
            pk=page_id,
            organization_id=context.organization_id,
        )
    except Page.DoesNotExist as error:
        raise PageNotFound from error
    if page.current_draft is None:
        return PageDraft(page, None, ())
    blocks = tuple(
        PageBlock.all_objects.filter(
            organization_id=context.organization_id,
            page_version_id=page.current_draft_id,
        ).order_by("position")
    )
    return PageDraft(page, page.current_draft, blocks)


@transaction.atomic
def save_draft(
    *,
    page_id: UUID,
    expected_version: int,
    blocks: list[dict[str, Any]],
    idempotency_key: str,
) -> MutationResult[PageVersion]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    normalized_blocks = [
        {
            "block_type": block["block_type"],
            "schema_version": block["schema_version"],
            "data": block["data"],
        }
        for block in blocks
    ]
    content_hash = canonical_json_hash(normalized_blocks)
    request_hash = canonical_json_hash(
        {
            "page_id": str(page_id),
            "expected_version": expected_version,
            "blocks": normalized_blocks,
        }
    )
    existing = PageVersion.all_objects.filter(
        organization_id=context.organization_id,
        page_id=page_id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        return MutationResult(_same_request(existing, request_hash), False)
    try:
        page = Page.all_objects.select_for_update().select_related("site").get(
            pk=page_id,
            organization_id=context.organization_id,
        )
    except Page.DoesNotExist as error:
        raise PageNotFound from error
    existing = PageVersion.all_objects.filter(
        organization_id=context.organization_id,
        page_id=page.id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        return MutationResult(_same_request(existing, request_hash), False)
    if page.version != expected_version:
        raise DraftVersionConflict

    actor = User.objects.get(pk=context.actor_id)
    version = PageVersion.all_objects.create(
        organization_id=context.organization_id,
        page=page,
        number=expected_version + 1,
        created_by=actor,
        idempotency_key=normalized_key,
        request_hash=request_hash,
        content_hash=content_hash,
    )
    PageBlock.all_objects.bulk_create(
        [
            PageBlock(
                organization_id=context.organization_id,
                page_version=version,
                position=position,
                block_type=block["block_type"],
                schema_version=block["schema_version"],
                data=block["data"],
            )
            for position, block in enumerate(normalized_blocks)
        ]
    )
    updated = Page.all_objects.filter(
        pk=page.id,
        organization_id=context.organization_id,
        version=expected_version,
    ).update(
        version=version.number,
        current_draft=version,
        updated_at=timezone.now(),
    )
    if updated != 1:
        raise DraftVersionConflict
    record_audit(
        organization=page.site.organization,
        action=PAGE_DRAFT_SAVED,
        actor=actor,
        target_type="page_version",
        target_id=version.id,
        metadata={
            "site_id": str(page.site_id),
            "page_id": str(page.id),
            "version": version.number,
            "block_count": len(normalized_blocks),
            "content_hash": version.content_hash,
        },
    )
    return MutationResult(version, True)


def _idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 120:
        raise SitesIdempotencyConflict
    return normalized


def _quota_idempotency_key(actor_id: UUID, idempotency_key: str) -> str:
    digest = canonical_json_hash(
        {"endpoint": "sites.create", "actor_id": str(actor_id), "key": idempotency_key}
    )
    return f"sites-create:{digest}"


def _same_request[T: Site | Page | PageVersion](value: T, request_hash: str) -> T:
    if value.request_hash != request_hash:
        raise SitesIdempotencyConflict
    return value
