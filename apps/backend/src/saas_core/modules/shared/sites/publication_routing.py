from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.organizations.models import OrganizationStatus

from .domains import InvalidHostname, normalize_hostname
from .models import Domain, DomainStatus, Publication


class PublicSiteNotFound(NotFound):
    default_detail = "Opublikowana strona nie istnieje dla tego hosta i ścieżki."
    default_code = "public_site_not_found"


@dataclass(frozen=True, slots=True)
class PublicPage:
    hostname: str
    canonical_hostname: str
    requested_path: str
    canonical_path: str
    locale: str
    publication: Publication
    page: dict[str, Any]

    @property
    def redirect_url(self) -> str | None:
        if self.hostname == self.canonical_hostname and self.requested_path == self.canonical_path:
            return None
        return f"{settings.PUBLIC_SITE_SCHEME}://{self.canonical_hostname}{self.canonical_path}"


def resolve_public_page(*, host: str, path: str) -> PublicPage:
    try:
        hostname = normalize_hostname(host, allow_port=True)
    except InvalidHostname as error:
        raise PublicSiteNotFound from error
    normalized_path = _normalize_path(path)
    domain = (
        Domain.all_objects.select_related("site__current_publication", "organization")
        .filter(
            hostname=hostname,
            status=DomainStatus.VERIFIED,
            organization__status=OrganizationStatus.ACTIVE,
            site__current_publication__isnull=False,
        )
        .first()
    )
    if domain is None or domain.site.current_publication is None:
        raise PublicSiteNotFound
    canonical = Domain.all_objects.filter(
        site_id=domain.site_id,
        status=DomainStatus.VERIFIED,
        is_canonical=True,
    ).first()
    if canonical is None:
        raise PublicSiteNotFound
    publication = domain.site.current_publication
    page, locale_document = _find_page(publication.snapshot, normalized_path)
    canonical_path = str(locale_document["canonical_path"])
    return PublicPage(
        hostname=hostname,
        canonical_hostname=canonical.hostname,
        requested_path=normalized_path,
        canonical_path=canonical_path,
        locale=str(locale_document["locale"]),
        publication=publication,
        page={**page, "selected_locale": locale_document},
    )


def public_page_payload(page: PublicPage) -> dict[str, Any]:
    selected_locale = page.page["selected_locale"]
    publication_snapshot = page.publication.snapshot
    canonical_origin = f"{settings.PUBLIC_SITE_SCHEME}://{page.canonical_hostname}"
    hreflang = {
        locale: f"{canonical_origin}{path}"
        for locale, path in page.page.get("hreflang", {}).items()
    }
    return {
        "publication_id": str(page.publication.id),
        "snapshot_hash": page.publication.snapshot_hash,
        "locale": page.locale,
        "canonical_url": f"{canonical_origin}{page.canonical_path}",
        "hreflang": hreflang,
        "x_default": f"{canonical_origin}{page.page['x_default']}",
        "title": selected_locale["title"],
        "description": selected_locale["description"],
        "social_title": selected_locale["social_title"],
        "social_description": selected_locale["social_description"],
        "design_tokens": publication_snapshot["design_tokens"],
        "blocks": page.page["blocks"],
    }


def _normalize_path(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValidationError({"path": ["Ścieżka musi zaczynać się od /. "]})
    if "\\" in value or "\x00" in value or "?" in value or "#" in value or "//" in value:
        raise ValidationError({"path": ["Ścieżka zawiera niedozwolone znaki."]})
    if len(value) > 2048:
        raise ValidationError({"path": ["Ścieżka jest za długa."]})
    return value


def _find_page(
    snapshot: dict[str, Any],
    requested_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_without_slash = requested_path.rstrip("/") or "/"
    for raw_page in snapshot.get("pages", []):
        if not isinstance(raw_page, dict):
            continue
        for raw_locale in raw_page.get("locales", []):
            if not isinstance(raw_locale, dict):
                continue
            candidate = str(raw_locale.get("path", ""))
            if candidate == normalized_without_slash:
                return raw_page, raw_locale
    raise PublicSiteNotFound
