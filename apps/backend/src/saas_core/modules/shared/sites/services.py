from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.conf import settings
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

from .block_contracts import validate_site_block
from .localization import SiteLocalizationReport, build_localization_report
from .models import (
    Page,
    PageBlock,
    PageTranslation,
    PageTranslationMutation,
    PageVersion,
    Site,
    canonical_json_hash,
)
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED, SITES_MAX

SITE_CREATED = "sites.site.created"
PAGE_CREATED = "sites.page.created"
PAGE_DRAFT_SAVED = "sites.page.draft_saved"
PAGE_TRANSLATION_SAVED = "sites.page.translation_saved"


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


@dataclass(frozen=True, slots=True)
class PageTranslations:
    page: Page
    supported_locales: tuple[str, ...]
    translations: tuple[PageTranslation, ...]


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
    if default_locale not in _supported_locales():
        raise UnsupportedSiteLocale
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
    return PageDraft(page, version, blocks)


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
    for block in normalized_blocks:
        validate_site_block(
            block_type=block["block_type"],
            schema_version=block["schema_version"],
            data=block["data"],
        )
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
    request_hash = canonical_json_hash(
        {
            "page_id": str(page_id),
            "locale": normalized_locale,
            "expected_version": expected_version,
            **values,
        }
    )
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
    if normalized_locale == site.default_locale and any(
        (
            allow_title_fallback,
            allow_description_fallback,
            allow_social_title_fallback,
            allow_social_description_fallback,
        )
    ):
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


def _supported_locales() -> tuple[str, ...]:
    return tuple(settings.SITES_SUPPORTED_LOCALES)


def _same_request[T: Site | Page | PageVersion](value: T, request_hash: str) -> T:
    if value.request_hash != request_hash:
        raise SitesIdempotencyConflict
    return value
