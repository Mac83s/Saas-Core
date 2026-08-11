from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .models import Page, PageTranslation, Site


@dataclass(frozen=True, slots=True)
class LocaleResolution:
    locale: str
    translation_id: UUID | None
    version: int | None
    slug: str | None
    path: str | None
    canonical_path: str | None
    title: str | None
    description: str | None
    social_title: str | None
    social_description: str | None
    fallback_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    complete: bool
    slug_locked: bool


@dataclass(frozen=True, slots=True)
class PageLocalization:
    page: Page
    locales: tuple[LocaleResolution, ...]
    hreflang: dict[str, str]
    x_default: str | None


@dataclass(frozen=True, slots=True)
class SiteLocalizationReport:
    site: Site
    supported_locales: tuple[str, ...]
    pages: tuple[PageLocalization, ...]
    ready_to_publish: bool


def localized_path(*, default_locale: str, locale: str, slug: str) -> str:
    if locale == default_locale:
        return f"/{slug}/"
    return f"/{locale}/{slug}/"


def build_localization_report(
    *,
    site: Site,
    pages: list[Page],
    translations: list[PageTranslation],
    supported_locales: tuple[str, ...],
) -> SiteLocalizationReport:
    by_page_locale = {
        (translation.page_id, translation.locale): translation
        for translation in translations
    }
    page_reports: list[PageLocalization] = []
    for page in pages:
        base = by_page_locale.get((page.id, site.default_locale))
        locale_reports = tuple(
            _resolve_locale(
                site=site,
                locale=locale,
                translation=by_page_locale.get((page.id, locale)),
                base=base,
            )
            for locale in supported_locales
        )
        hreflang = {
            locale_report.locale: locale_report.path
            for locale_report in locale_reports
            if locale_report.complete and locale_report.path is not None
        }
        page_reports.append(
            PageLocalization(
                page=page,
                locales=locale_reports,
                hreflang=hreflang,
                x_default=hreflang.get(site.default_locale),
            )
        )
    ready_to_publish = bool(page_reports) and all(
        any(
            locale.locale == site.default_locale and locale.complete
            for locale in page.locales
        )
        for page in page_reports
    )
    return SiteLocalizationReport(
        site=site,
        supported_locales=supported_locales,
        pages=tuple(page_reports),
        ready_to_publish=ready_to_publish,
    )


def _resolve_locale(
    *,
    site: Site,
    locale: str,
    translation: PageTranslation | None,
    base: PageTranslation | None,
) -> LocaleResolution:
    if translation is None:
        return LocaleResolution(
            locale=locale,
            translation_id=None,
            version=None,
            slug=None,
            path=None,
            canonical_path=None,
            title=None,
            description=None,
            social_title=None,
            social_description=None,
            fallback_fields=(),
            missing_fields=("translation", "slug", "title", "description"),
            complete=False,
            slug_locked=False,
        )

    fallback_fields: list[str] = []
    title = _resolve_field(translation, base, "title", fallback_fields)
    description = _resolve_field(translation, base, "description", fallback_fields)
    social_title = _resolve_field(translation, base, "social_title", fallback_fields)
    social_description = _resolve_field(
        translation,
        base,
        "social_description",
        fallback_fields,
    )
    social_title = social_title or title
    social_description = social_description or description
    missing_fields = tuple(
        field
        for field, value in (
            ("slug", translation.slug),
            ("title", title),
            ("description", description),
        )
        if not value
    )
    path = (
        localized_path(
            default_locale=site.default_locale,
            locale=locale,
            slug=translation.slug,
        )
        if translation.slug
        else None
    )
    return LocaleResolution(
        locale=locale,
        translation_id=translation.id,
        version=translation.version,
        slug=translation.slug,
        path=path,
        canonical_path=path,
        title=title or None,
        description=description or None,
        social_title=social_title or None,
        social_description=social_description or None,
        fallback_fields=tuple(fallback_fields),
        missing_fields=missing_fields,
        complete=not missing_fields,
        slug_locked=translation.slug_locked_at is not None,
    )


def _resolve_field(
    translation: PageTranslation,
    base: PageTranslation | None,
    field: str,
    fallback_fields: list[str],
) -> str:
    value = str(getattr(translation, field)).strip()
    if value:
        return value
    if translation.locale == translation.site.default_locale:
        return ""
    if not bool(getattr(translation, f"allow_{field}_fallback")) or base is None:
        return ""
    base_value = str(getattr(base, field)).strip()
    if not base_value and field == "social_title":
        base_value = base.title.strip()
    if not base_value and field == "social_description":
        base_value = base.description.strip()
    if base_value:
        fallback_fields.append(field)
    return base_value
