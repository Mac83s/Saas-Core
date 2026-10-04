"""A company's documents on its own site (ADR-072, slice 5f part 2).

Each document in force — the booking terms, the shop terms, the privacy and
the cancellation policy — has a page on every published site of its company,
at `/documents/<its name>/`: nobody publishes it, the site asks here through
the registry of public sources when no published page answers (as it asks
booking for a unit's `/stay/<unit>/`). The page is one block,
`core.document`, which only the server builds: the text a person approved,
never a copy somebody typed into a page.

A document is written per language and no language stands in for another
(ADR-073 §9, „Czytnik nie zastępuje języka”). So the page has the text where
the version in force has one; asked for in another language of the site it
says that the document has no version there and where it can be read — what
the booking form says when its terms have no text in the visitor's language —
and that page stays out of search and of the language alternates.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.conf import settings

from saas_core.modules.core.organizations.api import (
    PageAddress,
    SourcePage,
    SourcePageAddress,
)
from saas_core.modules.core.organizations.models import Organization

from .documents import _current_texts, _document, _in_force
from .models import DocumentKind, DocumentVersion
from .security import public_documents_context

#: The first segment of a document's page on the company's site, the same in
#: every language (as booking's `stay`, ADR-074 pkt 7).
PAGE_SEGMENT = "documents"
#: The block the page is: built here, written by nobody.
DOCUMENT_BLOCK = "core.document"
#: A document's address under the segment, the same in every language.
SLUGS: dict[str, str] = {
    "booking-terms": DocumentKind.BOOKING_TERMS,
    "shop-terms": DocumentKind.SHOP_TERMS,
    "privacy-policy": DocumentKind.PRIVACY_POLICY,
    "cancellation-policy": DocumentKind.CANCELLATION_POLICY,
}
#: What a document is called on the page, in the page's language — the words
#: the platform's own document page uses. A language without them reads
#: English.
KIND_NAMES: dict[str, dict[str, str]] = {
    DocumentKind.BOOKING_TERMS: {
        "pl": "Regulamin rezerwacji",
        "en": "Booking terms",
        "de": "Buchungsbedingungen",
        "es": "Condiciones de reserva",
        "ru": "Правила бронирования",
    },
    DocumentKind.SHOP_TERMS: {
        "pl": "Regulamin sklepu",
        "en": "Shop terms",
        "de": "Shop-Bedingungen",
        "es": "Condiciones de la tienda",
        "ru": "Правила магазина",
    },
    DocumentKind.PRIVACY_POLICY: {
        "pl": "Polityka prywatności",
        "en": "Privacy policy",
        "de": "Datenschutzerklärung",
        "es": "Política de privacidad",
        "ru": "Политика конфиденциальности",
    },
    DocumentKind.CANCELLATION_POLICY: {
        "pl": "Polityka anulowania",
        "en": "Cancellation policy",
        "de": "Stornobedingungen",
        "es": "Política de cancelación",
        "ru": "Правила отмены",
    },
}


def no_media(_organization_id: UUID) -> tuple[UUID, ...]:
    """A document shows no picture: nothing for media to keep or serve."""
    return ()


def kind_name(kind: str, locale: str) -> str:
    names = KIND_NAMES[kind]
    return names.get(locale) or names["en"]


def _native_name(code: str) -> str:
    entry = settings.LOCALE_REGISTRY.get(code)
    return entry.native_name if entry is not None else code


def _version_in_force(organization: Organization, kind: str) -> DocumentVersion | None:
    document = _document(organization.id, kind)
    return _in_force(document, organization.local_today()) if document else None


def site_page(
    organization_id: UUID, locale: str, slug: str, address: PageAddress | None = None
) -> SourcePage | None:
    """The page of the document at that address, in that language: the text
    in force there, or — the version having none in it — where it can be
    read. None: no such document, or no version of it in force today."""
    kind = SLUGS.get(slug)
    if kind is None:
        return None
    with public_documents_context(organization_id):
        organization = Organization.objects.get(pk=organization_id)
        version = _version_in_force(organization, kind)
        if version is None:
            return None
        texts = _current_texts(version)
    title = kind_name(kind, locale)
    data: dict[str, Any] = {
        "kind": kind,
        "title": title,
        "version": version.number,
        "effective_from": version.effective_from.isoformat(),
    }
    row = texts.get(locale)
    if row is not None:
        data["text"] = row.text
    else:
        # The languages that have the text, each at its own page on this site
        # — those the site is read in.
        data["elsewhere"] = [
            {"locale": code, "name": _native_name(code), "href": address(code)}
            for code in sorted(texts)
            if address is not None and address(code)
        ]
    return SourcePage(
        key=str(version.document_id),
        title=title,
        description=f"{title} — {organization.name}",
        blocks=[{"block_type": DOCUMENT_BLOCK, "schema_version": 1, "data": data}],
        locales=frozenset(texts),
        per_language=True,
    )


def site_pages(organization_id: UUID) -> list[SourcePageAddress]:
    """Every document that has a page now: the ones with a version in force,
    each in the languages that version has a text in."""
    pages: list[SourcePageAddress] = []
    with public_documents_context(organization_id):
        organization = Organization.objects.get(pk=organization_id)
        for slug, kind in SLUGS.items():
            version = _version_in_force(organization, kind)
            if version is None:
                continue
            texts = _current_texts(version)
            pages.append(
                SourcePageAddress(
                    slug=slug,
                    locales=frozenset(texts),
                    changed_at=max(row.accepted_at for row in texts.values())
                    if texts
                    else version.approved_at,
                    per_language=True,
                )
            )
    return pages
