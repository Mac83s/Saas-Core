"""A company's documents on its own site (ADR-072, „Rozstrzygnięcia plastra
5f, część 2”): each document in force has a page at `/documents/<name>/` that
nobody publishes, with the text a person approved, per language — a language
without the text says where the document can be read and shows no other
language's text — and nobody writes the block the page is made of."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.db import connection
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.shared.customers.documents import add_text
from saas_core.modules.shared.customers.site_pages import KIND_NAMES, SLUGS
from saas_core.modules.shared.sites.block_contracts import (
    ServerBuiltSiteBlock,
    site_block_contracts,
    validate_site_block,
)
from saas_core.modules.shared.sites.localization import first_segment_reserved
from saas_core.modules.shared.sites.publication_routing import localized_links
from test_booking import tenant
from test_booking_site_blocks import asked, block, page, published
from test_customers_documents import TEXT, approved, company, stepped_up, with_second_factor
from test_sites_api import create_page, create_site, csrf_value, sites_client

pytestmark = pytest.mark.django_db

PRIVACY = "privacy_policy"
TERMS = "booking_terms"


@pytest.fixture(autouse=True)
def quiet() -> None:
    cache.clear()


def site(owner: Membership, *, locale: str = "pl") -> str:
    return published(owner, [block("hero")], locale=locale)


def valid(data: dict[str, Any]) -> bool:
    """The block's data against its contract, as the renderer validates it."""
    return not list(site_block_contracts().validators["core.document"][1].iter_errors(data))


def sitemap(host: str) -> str:
    answer = APIClient().get(
        "/api/v1/public/site/sitemap.xml", HTTP_HOST=host, HTTP_ACCEPT="application/xml"
    )
    assert answer.status_code == 200, answer.content
    return str(answer.content.decode())


def test_a_document_in_force_has_a_page_on_the_companys_site(settings: Any) -> None:
    owner = with_second_factor(company("strona-dokument", ("pl",)))
    host = site(owner)

    # Nothing approved yet: no page, for a document or for a made-up name.
    assert asked(host, "/documents/privacy-policy/").status_code == 404
    assert asked(host, "/documents/nie-ma-takiego/").status_code == 404

    approved(owner)
    statements: list[str] = []

    def record(execute: Any, sql: str, params: Any, many: bool, context: Any) -> Any:
        statements.append(sql)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(record):
        answer = asked(host, "/documents/privacy-policy/")
    assert answer.status_code == 200, answer.content
    found = answer.json()

    (shown,) = found["blocks"]
    assert shown == {
        "block_type": "core.document",
        "schema_version": 1,
        "data": {
            "kind": PRIVACY,
            "title": "Polityka prywatności",
            "version": 1,
            "effective_from": owner.organization.local_today().isoformat(),
            "text": TEXT,
        },
    }
    # What the renderer is handed is the block's contract.
    assert valid(shown["data"])
    assert found["title"] == "Polityka prywatności"
    assert found["locale"] == "pl" and found["noindex"] is False
    origin = f"{settings.PUBLIC_SITE_SCHEME}://{host}"
    assert found["canonical_url"] == f"{origin}/documents/privacy-policy/"
    assert found["hreflang"] == {"pl": f"{origin}/documents/privacy-policy/"}
    # The host named the tenant; it is set before any document is read.
    tenant_set = next(i for i, sql in enumerate(statements) if "app.organization_id" in sql)
    first_read = next(i for i, sql in enumerate(statements) if "customers_customerdocument" in sql)
    assert tenant_set < first_read

    # Another document of the company has no version: its address stays 404,
    # and the sitemap names only the page that exists.
    assert asked(host, "/documents/booking-terms/").status_code == 404
    listed = sitemap(host)
    assert f"<loc>{origin}/documents/privacy-policy/</loc>" in listed
    assert "booking-terms" not in listed


def test_a_version_approved_for_later_has_no_page_until_its_day() -> None:
    owner = with_second_factor(company("strona-dokument-pozniej", ("pl",)))
    host = site(owner)
    approved(owner, kind=TERMS, effective_from=owner.organization.local_today() + timedelta(days=3))

    assert asked(host, "/documents/booking-terms/").status_code == 404
    assert "/documents/" not in sitemap(host)


def test_a_site_nobody_published_has_no_document_pages() -> None:
    owner = with_second_factor(company("strona-dokument-inna", ("pl",)))
    other = with_second_factor(company("strona-dokument-cudza", ("pl",)))
    approved(other)
    host = site(owner)

    # Another company's document is not this site's.
    assert asked(host, "/documents/privacy-policy/").status_code == 404


def test_a_language_without_the_text_says_where_the_document_can_be_read(
    settings: Any,
) -> None:
    settings.SITES_SUPPORTED_LOCALES = ("pl", "en", "de")
    owner = with_second_factor(company("strona-dokument-jezyki", ("pl", "en", "de")))
    host = site(owner)
    document = approved(owner, kind=TERMS)
    origin = f"{settings.PUBLIC_SITE_SCHEME}://{host}"

    # No text in English: the page answers at its English address — never a
    # move to the Polish text, never that text under an English address —
    # says nothing of the document's words and names where they are.
    english = page(host, "/en/documents/booking-terms/")
    (shown,) = english["blocks"]
    assert "text" not in shown["data"]
    assert shown["data"]["title"] == english["title"] == "Booking terms"
    assert shown["data"]["elsewhere"] == [
        {"locale": "pl", "name": "Polski", "href": "/documents/booking-terms/"}
    ]
    assert valid(shown["data"])
    assert TEXT not in str(english)
    # Out of search, and no language alternate names it.
    assert english["noindex"] is True
    assert english["canonical_url"] == f"{origin}/en/documents/booking-terms/"
    assert list(english["hreflang"]) == ["pl"]
    assert list(page(host, "/documents/booking-terms/")["hreflang"]) == ["pl"]
    assert "/en/documents/" not in sitemap(host)

    with tenant(owner), stepped_up():
        add_text(
            TERMS,
            number=1,
            locale="en",
            text="You book by the day.",
            expected_version=document["version"],
        )
    english = page(host, "/en/documents/booking-terms/")
    assert english["blocks"][0]["data"]["text"] == "You book by the day."
    assert "elsewhere" not in english["blocks"][0]["data"]
    assert english["noindex"] is False
    assert sorted(english["hreflang"]) == ["en", "pl"]
    assert english["x_default"] == f"{origin}/documents/booking-terms/"
    listed = sitemap(host)
    assert f"<loc>{origin}/en/documents/booking-terms/</loc>" in listed
    assert f'hreflang="en" href="{origin}/en/documents/booking-terms/"' in listed

    # German still has none: both languages that have the text are offered,
    # each at its own page of this site.
    german = page(host, "/de/documents/booking-terms/")
    assert german["blocks"][0]["data"]["elsewhere"] == [
        {"locale": "en", "name": "English", "href": "/en/documents/booking-terms/"},
        {"locale": "pl", "name": "Polski", "href": "/documents/booking-terms/"},
    ]
    assert german["title"] == "Buchungsbedingungen"
    assert "/de/documents/" not in listed

    # A language the site is not read in has no page at all.
    settings.SITES_SUPPORTED_LOCALES = ("pl", "en")
    cache.clear()
    assert asked(host, "/de/documents/booking-terms/").status_code == 404


def test_the_sites_own_language_is_no_exception(settings: Any) -> None:
    settings.SITES_SUPPORTED_LOCALES = ("pl", "en")
    owner = with_second_factor(company("strona-dokument-obca", ("pl", "en")))
    # The site speaks English first; the document was written in Polish.
    host = site(owner, locale="en")
    approved(owner)
    origin = f"{settings.PUBLIC_SITE_SCHEME}://{host}"

    own = page(host, "/documents/privacy-policy/")
    assert "text" not in own["blocks"][0]["data"]
    assert own["blocks"][0]["data"]["elsewhere"] == [
        {"locale": "pl", "name": "Polski", "href": "/pl/documents/privacy-policy/"}
    ]
    assert own["noindex"] is True
    polish = page(host, "/pl/documents/privacy-policy/")
    assert polish["blocks"][0]["data"]["text"] == TEXT
    assert polish["noindex"] is False and list(polish["hreflang"]) == ["pl"]
    # The sitemap lists the page where the text is, not the one that says
    # there is none.
    listed = sitemap(host)
    assert f"<loc>{origin}/pl/documents/privacy-policy/</loc>" in listed
    assert f"<loc>{origin}/documents/privacy-policy/</loc>" not in listed


def test_every_kind_has_an_address_and_a_name() -> None:
    assert sorted(SLUGS.values()) == sorted(KIND_NAMES)
    assert all(
        names.keys() >= {"pl", "en", "de", "es", "ru"} and all(names.values())
        for names in KIND_NAMES.values()
    )


def test_nobody_writes_the_document_block() -> None:
    contracts = site_block_contracts()
    assert contracts.server_built == {"core.document"}
    with pytest.raises(ServerBuiltSiteBlock):
        validate_site_block(
            block_type="core.document",
            schema_version=1,
            data={"kind": PRIVACY, "title": "T", "version": 1, "effective_from": "2026-10-04"},
        )

    # Through the API a draft that carries it is refused whole, and what a
    # connector is told it may write does not list it.
    client, _, _ = sites_client(slug="sites-document-block")
    created = create_site(client)
    made = create_page(client, created.data["id"])
    refused = client.put(
        f"/api/v1/sites/pages/{made.data['id']}/draft/",
        {
            "expected_version": 0,
            "blocks": [
                {
                    "block_type": "core.document",
                    "schema_version": 1,
                    "data": {
                        "kind": PRIVACY,
                        "title": "Polityka prywatności",
                        "version": 7,
                        "effective_from": "2026-10-04",
                        "text": "Nikt tego nie zatwierdził.",
                    },
                }
            ],
            "media_asset_ids": [],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="document-block-draft",
    )
    assert refused.status_code == 400, refused.content
    assert refused.json()["code"] == "server_built_site_block"
    capabilities = client.get("/api/v1/sites/capabilities/")
    assert capabilities.status_code == 200, capabilities.content
    offered = {row["block_type"] for row in capabilities.json()["block_schemas"]}
    assert "core.hero" in offered and "core.document" not in offered


def test_a_new_page_cannot_take_the_address_of_the_document_pages() -> None:
    assert first_segment_reserved("documents")
    assert not first_segment_reserved("dokumenty")


def test_a_link_to_a_records_page_follows_the_readers_language() -> None:
    blocks = [
        {
            "privacy_href": "/documents/privacy-policy/",
            "action": {"href": "/documents/booking-terms/?from=cennik#top"},
            "secondaryAction": {"href": "/stay/domek-1/"},
            "items": [{"href": "/o-nas/"}, {"href": "https://example.test/documents/x/"}],
        }
    ]

    assert localized_links(blocks, {"/o-nas": "/de/ueber-uns/"}, "/de") == [
        {
            "privacy_href": "/de/documents/privacy-policy/",
            "action": {"href": "/de/documents/booking-terms/?from=cennik#top"},
            "secondaryAction": {"href": "/de/stay/domek-1/"},
            "items": [{"href": "/de/ueber-uns/"}, {"href": "https://example.test/documents/x/"}],
        }
    ]
    # The site's own language has no prefix, and nothing moves.
    assert localized_links(blocks, {}) == blocks


def test_readiness_names_a_link_to_a_document_nobody_approved() -> None:
    client, organization, user = sites_client(slug="sites-missing-documents", role_key="owner")
    member = with_second_factor(Membership.objects.get(organization=organization, user=user))
    created = create_site(client)
    made = create_page(client, created.data["id"])

    def hero(action: str, secondary: str) -> dict[str, Any]:
        return {
            "block_type": "core.hero",
            "schema_version": 6,
            "data": {
                "title": "Domki nad jeziorem",
                "action": {"label": "Regulamin", "href": action},
                "secondaryAction": {"label": "Prywatność", "href": secondary},
                "layout": "centered",
            },
        }

    saved = client.put(
        f"/api/v1/sites/pages/{made.data['id']}/draft/",
        {
            "expected_version": 0,
            "blocks": [
                hero("/documents/booking-terms/", "/documents/privacy-policy/"),
                # A unit nobody shows, and an ordinary page of the site.
                hero("/stay/nie-ma-takiego/", "/kontakt/"),
            ],
            "media_asset_ids": [],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="missing-documents-draft",
    )
    assert saved.status_code in {200, 201}, saved.content

    def report() -> list[str]:
        answer = client.get(f"/api/v1/sites/{created.data['id']}/localization/")
        assert answer.status_code == 200, answer.content
        return list(answer.data["pages"][0]["missing_pages"])

    assert report() == [
        "/documents/booking-terms/",
        "/documents/privacy-policy/",
        "/stay/nie-ma-takiego/",
    ]
    # A person approves the privacy policy: its page is there now.
    approved(member)
    assert report() == ["/documents/booking-terms/", "/stay/nie-ma-takiego/"]
