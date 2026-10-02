"""Storage of a page body in another language (ADR-070, plan TL8b): versions
bound to the source version of their own page, append-only, and the
translation's body pointers naming only its own versions."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from django.db import DatabaseError, transaction

from saas_core.modules.core.organizations.erasure import erase_organization
from saas_core.modules.shared.sites.localized_bodies import extract_units, structure_signature
from saas_core.modules.shared.sites.models import (
    Page,
    PageBlock,
    PageLocaleVersion,
    PageTranslation,
    PageVersion,
    canonical_json_hash,
)
from test_sites_api import create_page, create_site, save_draft, save_translation, sites_client

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _page_with_english(slug: str) -> tuple[Any, Page, PageTranslation]:
    client, organization, _ = sites_client(slug=slug, role_key="owner")
    site_id = create_site(client).data["id"]
    page_id = create_page(client, site_id).data["id"]
    save_draft(client, page_id, expected_version=0, idempotency_key="d1", heading="Witaj")
    for locale, path in (("pl", "start"), ("en", "home")):
        save_translation(
            client,
            page_id,
            locale,
            expected_version=0,
            slug=path,
            title=path.title(),
            description="Opis",
            idempotency_key=f"t-{locale}",
        )
    page = Page.all_objects.get(pk=page_id)
    english = PageTranslation.all_objects.get(page=page, locale="en")
    return organization, page, english


def _version(page: Page, translation: PageTranslation, **overrides: Any) -> PageLocaleVersion:
    source = PageVersion.all_objects.get(pk=page.current_draft_id)
    blocks = [
        {"block_type": block.block_type, "schema_version": block.schema_version, "data": block.data}
        for block in PageBlock.all_objects.filter(page_version=source).order_by("position")
    ]
    units = {
        unit.key: {
            "text": "Welcome" if unit.text == "Witaj" else unit.text,
            "provenance": {"origin": "human", "source_hash": unit.source_hash},
        }
        for unit in extract_units(blocks)
    }
    values: dict[str, Any] = {
        "organization_id": page.organization_id,
        "site_id": page.site_id,
        "page": page,
        "translation": translation,
        "locale": translation.locale,
        "number": 1,
        "source_version": source,
        "structure_signature": structure_signature(blocks),
        "units": units,
        "content_hash": canonical_json_hash(units),
        "created_by_id": source.created_by_id,
        "idempotency_key": "body-1",
        "request_hash": "0" * 64,
        **overrides,
    }
    return PageLocaleVersion.all_objects.create(**values)


def test_a_language_version_is_bound_to_its_own_page_and_language():
    _, page, english = _page_with_english("locale-store")
    version = _version(page, english)
    assert version.units["0/heading"]["text"] == "Welcome"

    _, other_page, other_english = _page_with_english("locale-store-other")
    foreign_source = PageVersion.all_objects.get(pk=other_page.current_draft_id)
    polish = PageTranslation.all_objects.get(page=page, locale="pl")
    for translation, overrides in (
        (english, {"source_version": foreign_source}),
        (polish, {"locale": "en"}),
        (english, {"locale": "de"}),
        (english, {"locale": "DE"}),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            _version(page, translation, number=2, idempotency_key=str(overrides), **overrides)


def test_a_language_version_never_changes_and_pointers_name_only_their_own():
    _, page, english = _page_with_english("locale-append")
    version = _version(page, english)
    with pytest.raises(DatabaseError), transaction.atomic():
        PageLocaleVersion.all_objects.filter(pk=version.pk).update(units={})
    with pytest.raises(DatabaseError), transaction.atomic():
        PageLocaleVersion.all_objects.filter(pk=version.pk).delete()

    PageTranslation.all_objects.filter(pk=english.pk).update(
        body_current=version, body_version=1
    )
    polish = PageTranslation.all_objects.get(page=page, locale="pl")
    with pytest.raises(DatabaseError), transaction.atomic():
        PageTranslation.all_objects.filter(pk=polish.pk).update(body_pending=version)
    # Saving English text leaves the page's own lock alone.
    assert Page.all_objects.get(pk=page.pk).version == page.version


def test_an_organization_with_language_versions_can_be_erased():
    organization, page, english = _page_with_english("locale-erasure")
    version = _version(page, english)
    PageTranslation.all_objects.filter(pk=english.pk).update(
        body_current=version, body_pending=version, body_version=1
    )

    receipt = erase_organization(
        organization=organization, requested_by=None, reason="Synthetic test"
    )

    assert receipt.row_counts["sites.PageLocaleVersion"] == 1
    assert not PageLocaleVersion.all_objects.filter(organization_id=organization.id).exists()
