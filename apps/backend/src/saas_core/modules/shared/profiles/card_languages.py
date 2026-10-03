"""In which languages a company's catalogue card speaks (TL20).

A card is shown in another language only whole: every text it has (headline,
bio, each link label) translated by somebody, nothing standing in from the
source. Anything less is the card in its own language, with `noindex` on the
other language's page — a half-translated page is neither the translation nor
the original, and a search engine should index neither as one.

The answer is copied onto the catalogue row (`CatalogEntry.source_locale`,
`translated_locales`, `headline_by_locale`) because the listing, the sitemap
and the search index read only that row: opening every listed tenant to ask
would cost a query per entry and widen the public path (ADR-053 §4). The copy
follows every write of a card translation, every edit of the card and every
change of the company's languages.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from saas_core.content_protocol.provenance import ORIGIN_COPY
from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.locales import organization_content_locales
from saas_core.modules.core.organizations.models import Organization

from .models import CatalogEntry, PublicProfile, PublicProfileTranslation
from .search_index import enqueue
from .translation_source import link_key


def card_in_language(profile: PublicProfile, row: PublicProfileTranslation) -> dict[str, Any]:
    """The card's text in the row's language, with what stays in the source.
    The source's own text standing in for a translation (`copy`) is not one."""
    fallback: list[str] = []
    copied = {
        key
        for key, origin in (row.provenance or {}).items()
        if isinstance(origin, dict) and origin.get("origin") == ORIGIN_COPY
    }

    def text(field: str, translated: str, source: str, allowed: bool) -> str:
        if translated:
            return translated
        if source:
            fallback.append(field)
        return source if allowed else ""

    headline = text(
        "headline",
        "" if "headline" in copied else row.headline,
        profile.headline,
        row.allow_headline_fallback,
    )
    bio = text("bio", "" if "bio" in copied else row.bio, profile.bio, row.allow_bio_fallback)
    labels = {key: label for key, label in (row.link_labels or {}).items() if key not in copied}
    links = []
    for link in profile.links or ():
        key = link_key(link["url"])
        if key not in labels:
            fallback.append(key)
        links.append({"label": labels.get(key) or link["label"], "url": link["url"]})
    return {
        "headline": headline,
        "bio": bio,
        "links": links,
        "locale": row.locale,
        "fallback": fallback,
    }


def card_languages(profile: PublicProfile) -> dict[str, Any]:
    """The catalogue row's language columns for this card. Read inside the
    card's tenant: the translations are under policy."""
    organization = Organization.objects.get(pk=profile.organization_id)
    offered = organization_content_locales(organization)
    headlines: dict[str, str] = {}
    for row in PublicProfileTranslation.all_objects.filter(
        organization_id=profile.organization_id, profile=profile, locale__in=offered
    ).exclude(locale=profile.locale):
        shown = card_in_language(profile, row)
        if not shown["fallback"]:
            headlines[row.locale] = shown["headline"]
    ordered = [code for code in offered if code in headlines]
    return {
        "source_locale": profile.locale,
        "translated_locales": ordered,
        "headline_by_locale": {code: headlines[code] for code in ordered},
    }


def refresh_catalog_languages(organization_id: UUID) -> None:
    """A card translation or the company's languages changed: the catalogue
    row says where the card speaks now, and its search document follows."""
    entry = CatalogEntry.all_objects.filter(organization_id=organization_id).first()
    if entry is None:
        return
    with transaction.atomic():
        set_local_organization_id(organization_id)
        profile = PublicProfile.all_objects.filter(
            pk=entry.profile_id, organization_id=organization_id
        ).first()
        if profile is None:
            return
        values = card_languages(profile)
        CatalogEntry.all_objects.filter(pk=entry.pk).update(**values, updated_at=timezone.now())
    enqueue(organization_id)


def company_languages_changed(
    organization: Organization, before: tuple[str, ...], after: tuple[str, ...]
) -> None:
    """`register_public_locales_changed` handler: a language switched off
    leaves the card's languages at once, one switched back on returns."""
    refresh_catalog_languages(organization.id)
