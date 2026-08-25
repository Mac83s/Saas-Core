from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid7

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.api import (
    DomainEvent,
    ResourceReferenceConflict,
    ResourceReferenceRejected,
    copy_resource_references,
    dispatch_domain_event,
    list_resource_reference_ids,
    record_resource_references,
)
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import (
    TenantContext,
    require_tenant_context,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.tasks import issue_tenant_task_contract
from saas_core.modules.shared.billing.api import (
    FeatureOperation,
    authorize_entitled,
    consume_quota,
)
from saas_core.observability import correlation_id

from .block_contracts import validate_site_block
from .localization import SiteLocalizationReport, build_localization_report
from .models import (
    NavigationItem,
    Page,
    PageBlock,
    PageTranslation,
    PageTranslationMutation,
    PageVersion,
    Publication,
    Site,
    SiteOutboxEvent,
    canonical_json_hash,
)
from .permissions import SITE_CONTENT_EDIT, SITE_PUBLISH, SITES_ENABLED, SITES_MAX

SITE_CREATED = "sites.site.created"
PAGE_CREATED = "sites.page.created"
PAGE_DRAFT_SAVED = "sites.page.draft_saved"
PAGE_TRANSLATION_SAVED = "sites.page.translation_saved"
SITE_PUBLISHED = "sites.site.published"
SITE_ROLLED_BACK = "sites.site.rolled_back"
SITE_NAVIGATION_SAVED = "sites.navigation.saved"
SITE_PUBLISHED_EVENT = "sites.site.published"
MEDIA_ASSET_RESOURCE_TYPE = "shared.media.asset"
PAGE_VERSION_REFERENCE_OWNER = "sites.page_version"
PUBLICATION_REFERENCE_OWNER = "sites.publication"
PUBLICATION_SNAPSHOT_SCHEMA_VERSION = 1
DEFAULT_DESIGN_TOKENS = {
    "schemaVersion": 1,
    "palette": "neutral",
    "typography": "sans",
    "radius": "medium",
    "spacing": "comfortable",
}


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


class NavigationVersionConflict(APIException):
    status_code = 409
    default_detail = "Nawigacja została w międzyczasie zmieniona."
    default_code = "navigation_version_conflict"


class NavigationInvalidTree(APIException):
    status_code = 400
    default_detail = "Nawigacja zawiera nieprawidłowe drzewo pozycji."
    default_code = "navigation_invalid_tree"


class SiteMediaReferenceUnavailable(APIException):
    status_code = 409
    default_detail = "Wybrane media nie są gotowe albo nie są dostępne w tej organizacji."
    default_code = "site_media_reference_unavailable"


class SitePublicationNotReady(APIException):
    status_code = 409
    default_detail = "Site nie ma kompletnego draftu i bazowych tłumaczeń."
    default_code = "site_publication_not_ready"


class SitePublicationConflict(APIException):
    status_code = 409
    default_detail = "Zawartość site zmieniła się podczas publikacji."
    default_code = "site_publication_conflict"


class SitePublicationNotFound(NotFound):
    default_detail = "Publikacja nie istnieje."
    default_code = "site_publication_not_found"


class SitePublicationAlreadyCurrent(APIException):
    status_code = 409
    default_detail = "Wybrana publikacja jest już bieżąca."
    default_code = "site_publication_already_current"


class UnsupportedSiteLocale(APIException):
    status_code = 400
    default_detail = "Locale nie należy do profilu deploymentu."
    default_code = "unsupported_site_locale"


class TranslationFallbackConflict(APIException):
    status_code = 400
    default_detail = "Locale bazowe nie może korzystać z fallbacku."
    default_code = "translation_fallback_conflict"


class TranslationVersionConflict(APIException):
    status_code = 409
    default_detail = "Metadane tłumaczenia zostały w międzyczasie zmienione."
    default_code = "translation_version_conflict"


class TranslationSlugConflict(APIException):
    status_code = 409
    default_detail = "Slug jest już używany w tym site i locale."
    default_code = "translation_slug_conflict"


class TranslationSlugLocked(APIException):
    status_code = 409
    default_detail = "Slug opublikowanego tłumaczenia jest zablokowany."
    default_code = "translation_slug_locked"


class SiteNotFound(NotFound):
    default_detail = "Strona nie istnieje."
    default_code = "site_not_found"


class PageNotFound(NotFound):
    default_detail = "Podstrona nie istnieje."
    default_code = "page_not_found"


class PageVersionNotFound(NotFound):
    default_detail = "Wersja draftu nie istnieje."
    default_code = "page_version_not_found"


@dataclass(frozen=True, slots=True)
class MutationResult[T]:
    value: T
    created: bool


@dataclass(frozen=True, slots=True)
class PageDraft:
    page: Page
    version: PageVersion | None
    blocks: tuple[PageBlock, ...]
    media_asset_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class PageTranslations:
    page: Page
    supported_locales: tuple[str, ...]
    translations: tuple[PageTranslation, ...]


@dataclass(frozen=True, slots=True)
class SiteNavigation:
    site: Site
    items: tuple[NavigationItem, ...]


@dataclass(frozen=True, slots=True)
class SitePublication:
    publication: Publication
    created: bool


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
    subdomain_label: str | None = None,
) -> MutationResult[Site]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    if default_locale not in _supported_locales():
        raise UnsupportedSiteLocale
    normalized_key = _idempotency_key(idempotency_key)
    normalized_slug = slug.strip().lower()
    request_hash = canonical_json_hash({
        "name": name,
        "slug": normalized_slug,
        "default_locale": default_locale,
        "subdomain_label": subdomain_label or "",
    })
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
    from .domain_services import create_platform_domain

    platform_domain = create_platform_domain(
        site=site,
        actor=actor,
        idempotency_key=normalized_key,
        preferred_label=subdomain_label,
    )
    record_audit(
        organization=organization,
        action=SITE_CREATED,
        actor=actor,
        target_type="site",
        target_id=site.id,
        metadata={
            "slug": site.slug,
            "default_locale": site.default_locale,
            "platform_hostname": platform_domain.hostname,
        },
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
    request_hash = canonical_json_hash({
        "site_id": str(site_id),
        "name": name,
        "key": normalized_page_key,
    })
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
        return PageDraft(page, None, (), ())
    blocks = tuple(
        PageBlock.all_objects.filter(
            organization_id=context.organization_id,
            page_version_id=page.current_draft_id,
        ).order_by("position")
    )
    return PageDraft(
        page,
        page.current_draft,
        blocks,
        _page_version_media_asset_ids(context=context, version_id=page.current_draft.id),
    )


def get_draft_preview(*, page_id: UUID, version_id: UUID) -> PageDraft:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    try:
        page = Page.all_objects.get(
            pk=page_id,
            organization_id=context.organization_id,
        )
        version = PageVersion.all_objects.get(
            pk=version_id,
            page_id=page.id,
            organization_id=context.organization_id,
        )
    except (Page.DoesNotExist, PageVersion.DoesNotExist) as error:
        raise PageVersionNotFound from error
    blocks = tuple(
        PageBlock.all_objects.filter(
            organization_id=context.organization_id,
            page_version_id=version.id,
        ).order_by("position")
    )
    for block in blocks:
        validate_site_block(
            block_type=block.block_type,
            schema_version=block.schema_version,
            data=block.data,
        )
    return PageDraft(
        page,
        version,
        blocks,
        _page_version_media_asset_ids(context=context, version_id=version.id),
    )


@transaction.atomic
def save_draft(
    *,
    page_id: UUID,
    expected_version: int,
    blocks: list[dict[str, Any]],
    media_asset_ids: list[UUID],
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
    normalized_media_asset_ids = tuple(sorted(set(media_asset_ids), key=str))
    for block in normalized_blocks:
        validate_site_block(
            block_type=block["block_type"],
            schema_version=block["schema_version"],
            data=block["data"],
        )
    content_hash = canonical_json_hash({
        "blocks": normalized_blocks,
        "media_asset_ids": [str(asset_id) for asset_id in normalized_media_asset_ids],
    })
    request_hash = canonical_json_hash({
        "page_id": str(page_id),
        "expected_version": expected_version,
        "blocks": normalized_blocks,
        "media_asset_ids": [str(asset_id) for asset_id in normalized_media_asset_ids],
    })
    existing = PageVersion.all_objects.filter(
        organization_id=context.organization_id,
        page_id=page_id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        return MutationResult(_same_request(existing, request_hash), False)
    try:
        page = (
            Page.all_objects.select_for_update()
            .select_related("site")
            .get(
                pk=page_id,
                organization_id=context.organization_id,
            )
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
    PageBlock.all_objects.bulk_create([
        PageBlock(
            organization_id=context.organization_id,
            page_version=version,
            position=position,
            block_type=block["block_type"],
            schema_version=block["schema_version"],
            data=block["data"],
        )
        for position, block in enumerate(normalized_blocks)
    ])
    try:
        record_resource_references(
            context=context,
            resource_type=MEDIA_ASSET_RESOURCE_TYPE,
            owner_type=PAGE_VERSION_REFERENCE_OWNER,
            owner_id=version.id,
            resource_ids=normalized_media_asset_ids,
        )
    except ResourceReferenceRejected as error:
        raise SiteMediaReferenceUnavailable from error
    except ResourceReferenceConflict as error:
        raise SitesIdempotencyConflict from error
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
            "media_asset_count": len(normalized_media_asset_ids),
            "content_hash": version.content_hash,
        },
    )
    return MutationResult(version, True)


def list_page_translations(*, page_id: UUID) -> PageTranslations:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    try:
        page = Page.all_objects.select_related("site").get(
            pk=page_id,
            organization_id=context.organization_id,
        )
    except Page.DoesNotExist as error:
        raise PageNotFound from error
    translations = tuple(
        PageTranslation.all_objects.filter(
            organization_id=context.organization_id,
            page_id=page.id,
        )
        .select_related("site")
        .order_by("locale")
    )
    return PageTranslations(page, _supported_locales(), translations)


@transaction.atomic
def save_page_translation(
    *,
    page_id: UUID,
    locale: str,
    expected_version: int,
    slug: str,
    title: str,
    description: str,
    social_title: str,
    social_description: str,
    allow_title_fallback: bool,
    allow_description_fallback: bool,
    allow_social_title_fallback: bool,
    allow_social_description_fallback: bool,
    idempotency_key: str,
) -> MutationResult[PageTranslation]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    normalized_locale = locale.strip().lower()
    if normalized_locale not in _supported_locales():
        raise UnsupportedSiteLocale
    normalized_key = _idempotency_key(idempotency_key)
    values: dict[str, str | bool] = {
        "slug": slug.strip().lower(),
        "title": title.strip(),
        "description": description.strip(),
        "social_title": social_title.strip(),
        "social_description": social_description.strip(),
        "allow_title_fallback": allow_title_fallback,
        "allow_description_fallback": allow_description_fallback,
        "allow_social_title_fallback": allow_social_title_fallback,
        "allow_social_description_fallback": allow_social_description_fallback,
    }
    request_hash = canonical_json_hash({
        "page_id": str(page_id),
        "locale": normalized_locale,
        "expected_version": expected_version,
        **values,
    })
    try:
        page = (
            Page.all_objects.select_for_update()
            .select_related("site__organization")
            .get(pk=page_id, organization_id=context.organization_id)
        )
    except Page.DoesNotExist as error:
        raise PageNotFound from error
    site = Site.all_objects.select_for_update().get(
        pk=page.site_id,
        organization_id=context.organization_id,
    )
    if site.default_locale not in _supported_locales():
        raise UnsupportedSiteLocale
    if normalized_locale == site.default_locale and any((
        allow_title_fallback,
        allow_description_fallback,
        allow_social_title_fallback,
        allow_social_description_fallback,
    )):
        raise TranslationFallbackConflict

    translation = (
        PageTranslation.all_objects.select_for_update()
        .filter(
            organization_id=context.organization_id,
            page_id=page.id,
            locale=normalized_locale,
        )
        .first()
    )
    if translation is not None:
        receipt = PageTranslationMutation.all_objects.filter(
            organization_id=context.organization_id,
            translation_id=translation.id,
            created_by_id=context.actor_id,
            idempotency_key=normalized_key,
        ).first()
        if receipt is not None:
            if receipt.request_hash != request_hash:
                raise SitesIdempotencyConflict
            return MutationResult(translation, False)
    if translation is None and expected_version != 0:
        raise TranslationVersionConflict
    if translation is not None and translation.version != expected_version:
        raise TranslationVersionConflict
    if (
        translation is not None
        and translation.slug_locked_at is not None
        and translation.slug != values["slug"]
    ):
        raise TranslationSlugLocked
    duplicate_slug = PageTranslation.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site.id,
        locale=normalized_locale,
        slug=values["slug"],
    )
    if translation is not None:
        duplicate_slug = duplicate_slug.exclude(pk=translation.id)
    if duplicate_slug.exists():
        raise TranslationSlugConflict

    actor = User.objects.get(pk=context.actor_id)
    resulting_version = expected_version + 1
    if translation is None:
        translation = PageTranslation.all_objects.create(
            organization_id=context.organization_id,
            site=site,
            page=page,
            locale=normalized_locale,
            version=resulting_version,
            **values,
        )
    else:
        for field, value in values.items():
            setattr(translation, field, value)
        translation.version = resulting_version
        translation.save(update_fields=[*values.keys(), "version", "updated_at"])
    PageTranslationMutation.all_objects.create(
        organization_id=context.organization_id,
        translation=translation,
        created_by=actor,
        idempotency_key=normalized_key,
        request_hash=request_hash,
        resulting_version=resulting_version,
    )
    record_audit(
        organization=page.site.organization,
        action=PAGE_TRANSLATION_SAVED,
        actor=actor,
        target_type="page_translation",
        target_id=translation.id,
        metadata={
            "site_id": str(site.id),
            "page_id": str(page.id),
            "locale": normalized_locale,
            "version": resulting_version,
            "fallback_fields": [
                field.removeprefix("allow_").removesuffix("_fallback")
                for field, value in values.items()
                if field.startswith("allow_") and value
            ],
        },
    )
    return MutationResult(translation, True)


def get_site_localization_report(*, site_id: UUID) -> SiteLocalizationReport:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    try:
        site = Site.all_objects.get(
            pk=site_id,
            organization_id=context.organization_id,
        )
    except Site.DoesNotExist as error:
        raise SiteNotFound from error
    supported_locales = _supported_locales()
    if site.default_locale not in supported_locales:
        raise UnsupportedSiteLocale
    pages = list(
        Page.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site.id,
        ).order_by("key", "id")
    )
    translations = list(
        PageTranslation.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site.id,
            locale__in=supported_locales,
        ).select_related("site")
    )
    return build_localization_report(
        site=site,
        pages=pages,
        translations=translations,
        supported_locales=supported_locales,
    )


def list_site_publications(
    *,
    site_id: UUID,
    cursor: UUID | None,
    limit: int,
) -> tuple[list[Publication], UUID | None]:
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
    queryset = Publication.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site_id,
    ).select_related("created_by", "source_publication")
    if cursor is not None:
        cursor_publication = queryset.filter(pk=cursor).first()
        if cursor_publication is None:
            raise SitePublicationNotFound
        queryset = queryset.filter(sequence__lt=cursor_publication.sequence)
    rows = list(queryset.order_by("-sequence")[: limit + 1])
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return rows[:limit], next_cursor


def get_site_navigation(*, site_id: UUID) -> SiteNavigation:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    site = Site.all_objects.filter(
        pk=site_id,
        organization_id=context.organization_id,
    ).first()
    if site is None:
        raise SiteNotFound
    items = tuple(
        NavigationItem.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site_id,
        ).order_by("position", "id")
    )
    return SiteNavigation(site=site, items=items)


@transaction.atomic
def save_site_navigation(
    *,
    site_id: UUID,
    expected_version: int,
    items: list[dict[str, Any]],
) -> SiteNavigation:
    """Replaces the whole menu.

    Navigation is one object even though it is stored as rows: moving an entry
    renumbers its siblings, so a per-entry API would let two editors interleave
    partial moves into a tree neither of them intended. The version guards the
    menu as a whole.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    site = (
        Site.all_objects.select_for_update()
        .filter(pk=site_id, organization_id=context.organization_id)
        .first()
    )
    if site is None:
        raise SiteNotFound
    if site.navigation_version != expected_version:
        raise NavigationVersionConflict

    page_ids = [UUID(str(item["page_id"])) for item in items]
    if len(set(page_ids)) != len(page_ids):
        raise NavigationInvalidTree
    known_pages = set(
        Page.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site_id,
            pk__in=page_ids,
        ).values_list("pk", flat=True)
    )
    if known_pages != set(page_ids):
        raise NavigationInvalidTree

    parents = {
        UUID(str(item["page_id"])): (
            UUID(str(item["parent_page_id"]))
            if item.get("parent_page_id") is not None
            else None
        )
        for item in items
    }
    for page_id, parent_id in parents.items():
        if parent_id is None:
            continue
        if parent_id not in parents or parent_id == page_id:
            raise NavigationInvalidTree
        # One level of nesting, matching what the editor and the public menu
        # render. A deeper tree would publish links the renderer cannot show.
        if parents[parent_id] is not None:
            raise NavigationInvalidTree

    NavigationItem.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site_id,
    ).delete()
    created: dict[UUID, NavigationItem] = {}
    for position, item in enumerate(items):
        page_id = UUID(str(item["page_id"]))
        if parents[page_id] is not None:
            continue
        created[page_id] = NavigationItem.all_objects.create(
            organization_id=context.organization_id,
            site_id=site_id,
            page_id=page_id,
            parent=None,
            position=position,
            visible=bool(item.get("visible", True)),
        )
    for position, item in enumerate(items):
        page_id = UUID(str(item["page_id"]))
        parent_page_id = parents[page_id]
        if parent_page_id is None:
            continue
        created[page_id] = NavigationItem.all_objects.create(
            organization_id=context.organization_id,
            site_id=site_id,
            page_id=page_id,
            parent=created[parent_page_id],
            position=position,
            visible=bool(item.get("visible", True)),
        )

    site.navigation_version += 1
    site.save(update_fields=["navigation_version", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=SITE_NAVIGATION_SAVED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="site",
        target_id=site.id,
        metadata={
            "navigation_version": site.navigation_version,
            "items": len(items),
        },
    )
    return SiteNavigation(
        site=site,
        items=tuple(
            NavigationItem.all_objects.filter(
                organization_id=context.organization_id,
                site_id=site_id,
            ).order_by("position", "id")
        ),
    )


@transaction.atomic
def publish_site(*, site_id: UUID, idempotency_key: str) -> SitePublication:
    context = authorize_entitled(SITE_PUBLISH, SITES_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    try:
        initial_site = Site.all_objects.get(
            pk=site_id,
            organization_id=context.organization_id,
        )
    except Site.DoesNotExist as error:
        raise SiteNotFound from error
    existing = _existing_site_publication(
        context=context,
        site_id=site_id,
        idempotency_key=normalized_key,
    )
    if existing is not None:
        return existing

    pages = list(
        Page.all_objects.select_for_update(of=("self",))
        .select_related("current_draft")
        .filter(
            organization_id=context.organization_id,
            site_id=initial_site.id,
        )
        .order_by("id")
    )
    site = Site.all_objects.select_for_update().get(
        pk=initial_site.id,
        organization_id=context.organization_id,
    )
    existing = _existing_site_publication(
        context=context,
        site_id=site.id,
        idempotency_key=normalized_key,
    )
    if existing is not None:
        return existing
    current_page_ids = tuple(
        Page.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site.id,
        )
        .order_by("id")
        .values_list("id", flat=True)
    )
    if current_page_ids != tuple(page.id for page in pages):
        raise SitePublicationConflict
    if not pages or any(page.current_draft_id is None for page in pages):
        raise SitePublicationNotReady

    translations = list(
        PageTranslation.all_objects.select_for_update()
        .filter(
            organization_id=context.organization_id,
            site_id=site.id,
            locale__in=_supported_locales(),
        )
        .select_related("site")
        .order_by("page_id", "locale")
    )
    localization = build_localization_report(
        site=site,
        pages=pages,
        translations=translations,
        supported_locales=_supported_locales(),
    )
    if not localization.ready_to_publish:
        raise SitePublicationNotReady

    version_ids = tuple(_current_version_id(page) for page in pages)
    blocks = list(
        PageBlock.all_objects.filter(
            organization_id=context.organization_id,
            page_version_id__in=version_ids,
        ).order_by("page_version_id", "position")
    )
    blocks_by_version: dict[UUID, list[PageBlock]] = {}
    for block in blocks:
        validate_site_block(
            block_type=block.block_type,
            schema_version=block.schema_version,
            data=block.data,
        )
        blocks_by_version.setdefault(block.page_version_id, []).append(block)

    page_media_ids = {
        page.id: _page_version_media_asset_ids(
            context=context,
            version_id=_current_version_id(page),
        )
        for page in pages
    }
    all_media_ids = tuple(
        sorted(
            {asset_id for asset_ids in page_media_ids.values() for asset_id in asset_ids},
            key=str,
        )
    )
    snapshot = _publication_snapshot(
        site=site,
        pages=pages,
        blocks_by_version=blocks_by_version,
        localization=localization,
        page_media_ids=page_media_ids,
        navigation=_navigation_snapshot(
            site=site,
            organization_id=context.organization_id,
            published_page_ids={page.id for page in pages},
        ),
    )
    previous = (
        Publication.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site.id,
        )
        .order_by("-sequence")
        .first()
    )
    actor = User.objects.get(pk=context.actor_id)
    publication = Publication.all_objects.create(
        organization_id=context.organization_id,
        site=site,
        sequence=(previous.sequence + 1 if previous is not None else 1),
        snapshot_schema_version=PUBLICATION_SNAPSHOT_SCHEMA_VERSION,
        snapshot=snapshot,
        snapshot_hash="",
        created_by=actor,
        idempotency_key=normalized_key,
    )
    try:
        record_resource_references(
            context=context,
            resource_type=MEDIA_ASSET_RESOURCE_TYPE,
            owner_type=PUBLICATION_REFERENCE_OWNER,
            owner_id=publication.id,
            resource_ids=all_media_ids,
        )
    except ResourceReferenceRejected as error:
        raise SiteMediaReferenceUnavailable from error
    except ResourceReferenceConflict as error:
        raise SitesIdempotencyConflict from error

    published_at = timezone.now()
    published_translation_ids = [
        locale.translation_id
        for page in localization.pages
        for locale in page.locales
        if locale.complete and locale.translation_id is not None
    ]
    PageTranslation.all_objects.filter(
        organization_id=context.organization_id,
        id__in=published_translation_ids,
        slug_locked_at__isnull=True,
    ).update(slug_locked_at=published_at, updated_at=published_at)
    Site.all_objects.filter(
        pk=site.id,
        organization_id=context.organization_id,
    ).update(current_publication=publication, updated_at=published_at)
    from .tls import invalidate_site_tls_decisions

    transaction.on_commit(lambda: invalidate_site_tls_decisions(site_id=site.id))

    active_correlation_id = correlation_id.get()
    event = SiteOutboxEvent.all_objects.create(
        organization_id=context.organization_id,
        publication=publication,
        event_type=SITE_PUBLISHED_EVENT,
        version=1,
        actor=actor,
        correlation_id=UUID(active_correlation_id) if active_correlation_id else uuid7(),
        causation_id=f"sites-publish:{publication.id}",
        payload={
            "site_id": str(site.id),
            "publication_id": str(publication.id),
            "sequence": publication.sequence,
            "snapshot_hash": publication.snapshot_hash,
        },
    )
    _schedule_site_outbox_delivery(event)
    record_audit(
        organization=site.organization,
        action=SITE_PUBLISHED,
        actor=actor,
        target_type="publication",
        target_id=publication.id,
        metadata={
            "site_id": str(site.id),
            "sequence": publication.sequence,
            "snapshot_hash": publication.snapshot_hash,
            "page_count": len(pages),
            "media_asset_count": len(all_media_ids),
        },
    )
    return SitePublication(publication, True)


@transaction.atomic
def rollback_site(
    *,
    site_id: UUID,
    publication_id: UUID,
    idempotency_key: str,
) -> SitePublication:
    context = authorize_entitled(SITE_PUBLISH, SITES_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    existing = _existing_site_rollback(
        context=context,
        site_id=site_id,
        source_publication_id=publication_id,
        idempotency_key=normalized_key,
    )
    if existing is not None:
        return existing

    try:
        site = Site.all_objects.select_for_update().get(
            pk=site_id,
            organization_id=context.organization_id,
        )
        source = Publication.all_objects.get(
            pk=publication_id,
            site_id=site.id,
            organization_id=context.organization_id,
        )
    except Site.DoesNotExist as error:
        raise SiteNotFound from error
    except Publication.DoesNotExist as error:
        raise SitePublicationNotFound from error
    existing = _existing_site_rollback(
        context=context,
        site_id=site.id,
        source_publication_id=source.id,
        idempotency_key=normalized_key,
    )
    if existing is not None:
        return existing
    if site.current_publication_id == source.id:
        raise SitePublicationAlreadyCurrent

    previous = (
        Publication.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site.id,
        )
        .order_by("-sequence")
        .first()
    )
    if previous is None:
        raise SitePublicationNotFound
    actor = User.objects.get(pk=context.actor_id)
    publication = Publication.all_objects.create(
        organization_id=context.organization_id,
        site=site,
        sequence=previous.sequence + 1,
        snapshot_schema_version=source.snapshot_schema_version,
        snapshot=source.snapshot,
        snapshot_hash="",
        created_by=actor,
        source_publication=source,
        idempotency_key=normalized_key,
    )
    try:
        media_ids = copy_resource_references(
            context=context,
            resource_type=MEDIA_ASSET_RESOURCE_TYPE,
            owner_type=PUBLICATION_REFERENCE_OWNER,
            source_owner_id=source.id,
            target_owner_id=publication.id,
        )
    except ResourceReferenceRejected as error:
        raise SiteMediaReferenceUnavailable from error
    except ResourceReferenceConflict as error:
        raise SitesIdempotencyConflict from error

    activated_at = timezone.now()
    Site.all_objects.filter(
        pk=site.id,
        organization_id=context.organization_id,
    ).update(current_publication=publication, updated_at=activated_at)
    from .tls import invalidate_site_tls_decisions

    transaction.on_commit(lambda: invalidate_site_tls_decisions(site_id=site.id))
    active_correlation_id = correlation_id.get()
    event = SiteOutboxEvent.all_objects.create(
        organization_id=context.organization_id,
        publication=publication,
        event_type=SITE_PUBLISHED_EVENT,
        version=1,
        actor=actor,
        correlation_id=UUID(active_correlation_id) if active_correlation_id else uuid7(),
        causation_id=f"sites-rollback:{publication.id}",
        payload={
            "site_id": str(site.id),
            "publication_id": str(publication.id),
            "sequence": publication.sequence,
            "snapshot_hash": publication.snapshot_hash,
            "source_publication_id": str(source.id),
        },
    )
    _schedule_site_outbox_delivery(event)
    record_audit(
        organization=site.organization,
        action=SITE_ROLLED_BACK,
        actor=actor,
        target_type="publication",
        target_id=publication.id,
        metadata={
            "site_id": str(site.id),
            "sequence": publication.sequence,
            "snapshot_hash": publication.snapshot_hash,
            "source_publication_id": str(source.id),
            "media_asset_count": len(media_ids),
        },
    )
    return SitePublication(publication, True)


def _schedule_site_outbox_delivery(event: SiteOutboxEvent) -> None:
    task_contract = issue_tenant_task_contract(causation_id=f"sites-outbox:{event.id}")

    def enqueue_outbox() -> None:
        from .tasks import publish_site_outbox_event_task

        publish_site_outbox_event_task.delay(str(event.id), task_contract)

    transaction.on_commit(enqueue_outbox, robust=True)


def _existing_site_publication(
    *,
    context: TenantContext,
    site_id: UUID,
    idempotency_key: str,
) -> SitePublication | None:
    publication = Publication.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site_id,
        created_by_id=context.actor_id,
        idempotency_key=idempotency_key,
    ).first()
    if publication is None:
        return None
    pending_event = SiteOutboxEvent.all_objects.filter(
        organization_id=context.organization_id,
        publication_id=publication.id,
        published_at__isnull=True,
    ).first()
    if pending_event is not None:
        _schedule_site_outbox_delivery(pending_event)
    return SitePublication(publication, False)


def _existing_site_rollback(
    *,
    context: TenantContext,
    site_id: UUID,
    source_publication_id: UUID,
    idempotency_key: str,
) -> SitePublication | None:
    publication = Publication.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site_id,
        created_by_id=context.actor_id,
        idempotency_key=idempotency_key,
    ).first()
    if publication is None:
        return None
    if publication.source_publication_id != source_publication_id:
        raise SitesIdempotencyConflict
    pending_event = SiteOutboxEvent.all_objects.filter(
        organization_id=context.organization_id,
        publication_id=publication.id,
        published_at__isnull=True,
    ).first()
    if pending_event is not None:
        _schedule_site_outbox_delivery(pending_event)
    return SitePublication(publication, False)


@transaction.atomic
def publish_site_outbox_event(*, event_id: UUID) -> SiteOutboxEvent | None:
    context = require_tenant_context()
    event = (
        SiteOutboxEvent.all_objects.select_for_update()
        .filter(
            pk=event_id,
            organization_id=context.organization_id,
        )
        .first()
    )
    if event is None or event.published_at is not None:
        return event
    dispatch_domain_event(
        context=context,
        event=DomainEvent(
            id=event.id,
            event_type=event.event_type,
            version=event.version,
            organization_id=event.organization_id,
            actor_id=event.actor_id,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            payload=event.payload,
        ),
    )
    event.published_at = timezone.now()
    event.save(update_fields=["published_at"])
    return event


def _idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 120:
        raise SitesIdempotencyConflict
    return normalized


def _quota_idempotency_key(actor_id: UUID, idempotency_key: str) -> str:
    digest = canonical_json_hash({
        "endpoint": "sites.create",
        "actor_id": str(actor_id),
        "key": idempotency_key,
    })
    return f"sites-create:{digest}"


def _supported_locales() -> tuple[str, ...]:
    return tuple(settings.SITES_SUPPORTED_LOCALES)


def _page_version_media_asset_ids(
    *,
    context: TenantContext,
    version_id: UUID,
) -> tuple[UUID, ...]:
    return list_resource_reference_ids(
        context=context,
        resource_type=MEDIA_ASSET_RESOURCE_TYPE,
        owner_type=PAGE_VERSION_REFERENCE_OWNER,
        owner_id=version_id,
    )


def _navigation_snapshot(
    *,
    site: Site,
    organization_id: UUID,
    published_page_ids: set[UUID],
) -> list[dict[str, Any]]:
    """The menu as published: hidden entries and entries pointing at pages that
    did not make this publication are dropped, so the snapshot never links to
    something the renderer cannot show. A child whose parent was dropped is
    dropped with it rather than silently promoted to the top level."""
    items = list(
        NavigationItem.all_objects.filter(
            organization_id=organization_id,
            site_id=site.id,
            visible=True,
        ).order_by("position", "id")
    )
    kept = {
        item.id: item
        for item in items
        if item.page_id in published_page_ids
    }

    def reachable(item: NavigationItem) -> bool:
        seen: set[UUID] = set()
        current = item
        while current.parent_id is not None:
            if current.parent_id in seen or current.parent_id not in kept:
                return False
            seen.add(current.parent_id)
            current = kept[current.parent_id]
        return True

    # Addressed by page, not by navigation-item id: the public payload and the
    # panel both speak in pages, and mixing the two id spaces silently drops
    # every nested entry when the renderer tries to match them up.
    return [
        {
            "page_id": str(item.page_id),
            "parent_page_id": (
                str(kept[item.parent_id].page_id) if item.parent_id else None
            ),
            "position": item.position,
        }
        for item in items
        if item.id in kept and reachable(item)
    ]


def _publication_snapshot(
    *,
    site: Site,
    pages: list[Page],
    blocks_by_version: dict[UUID, list[PageBlock]],
    localization: SiteLocalizationReport,
    page_media_ids: dict[UUID, tuple[UUID, ...]],
    navigation: list[dict[str, Any]],
) -> dict[str, Any]:
    localization_by_page = {page.page.id: page for page in localization.pages}
    return {
        "site_id": str(site.id),
        "site_slug": site.slug,
        "default_locale": site.default_locale,
        "design_tokens": DEFAULT_DESIGN_TOKENS,
        "navigation": navigation,
        "pages": [
            {
                "page_id": str(page.id),
                "key": page.key,
                "version_id": str(_current_version_id(page)),
                "version": page.current_draft.number if page.current_draft else 0,
                "blocks": [
                    {
                        "block_type": block.block_type,
                        "schema_version": block.schema_version,
                        "data": block.data,
                    }
                    for block in blocks_by_version.get(_current_version_id(page), [])
                ],
                "media_asset_ids": [str(asset_id) for asset_id in page_media_ids.get(page.id, ())],
                "locales": [
                    {
                        "locale": locale.locale,
                        "translation_id": (
                            str(locale.translation_id)
                            if locale.translation_id is not None
                            else None
                        ),
                        "version": locale.version,
                        "slug": locale.slug,
                        "path": locale.path,
                        "canonical_path": locale.canonical_path,
                        "title": locale.title,
                        "description": locale.description,
                        "social_title": locale.social_title,
                        "social_description": locale.social_description,
                        "fallback_fields": list(locale.fallback_fields),
                    }
                    for locale in localization_by_page[page.id].locales
                    if locale.complete
                ],
                "hreflang": localization_by_page[page.id].hreflang,
                "x_default": localization_by_page[page.id].x_default,
            }
            for page in pages
        ],
    }


def _current_version_id(page: Page) -> UUID:
    if page.current_draft_id is None:
        raise SitePublicationNotReady
    return page.current_draft_id


def _same_request[T: Site | Page | PageVersion](value: T, request_hash: str) -> T:
    if value.request_hash != request_hash:
        raise SitesIdempotencyConflict
    return value
