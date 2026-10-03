"""The structured data of a public page (TL18, ADR-071 pkt 16): one JSON-LD
graph, with the company as one `#organization` in every language — the facts
its business card stated when the site was published."""

from __future__ import annotations

import re
from typing import Any

import pytest
from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from saas_core.modules.shared.profiles.catalog_contract import categories
from saas_core.modules.shared.profiles.models import PublicProfile
from saas_core.modules.shared.sites.models import Publication, Site
from saas_core.modules.shared.sites.seo_graph import organization_node, page_graph
from test_site_language_publication import _get, _publish
from test_sites_api import rollback_site_request
from test_sites_blog_languages import Blog, _translate_entry
from test_sites_sitemap_head import _sitemap, _two_language_site, _url

pytestmark = pytest.mark.django_db
ORIGIN = "https://studio.example.test"


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _graph(host: str, path: str) -> dict[str, dict[str, Any]]:
    """The page's graph by node type (the first type of a node with two)."""
    response = _get(host, path)
    assert response.status_code == 200, response.content
    data = response.json()["structured_data"]
    assert data["@context"] == "https://schema.org"
    nodes: dict[str, dict[str, Any]] = {}
    for node in data["@graph"]:
        kind = node["@type"] if isinstance(node["@type"], str) else node["@type"][0]
        assert kind not in nodes, kind
        nodes[kind] = node
    return nodes


def _card(site_id: str, **fields: Any) -> PublicProfile:
    site = Site.all_objects.get(pk=site_id)
    return PublicProfile.all_objects.create(
        organization_id=site.organization_id,
        subject_kind="organization",
        display_name="Studio Projektowe Ewa",
        **fields,
    )


def _page(**overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "origin": ORIGIN,
        "site_name": "Studio",
        "locale": "pl",
        "canonical_url": f"{ORIGIN}/oferta/",
        "title": "Oferta",
        "description": "Co robimy",
        "breadcrumbs": [{"title": "Start", "path": "/"}, {"title": "Oferta", "path": "/oferta/"}],
        "blocks": [],
        "article": None,
        "image": None,
        "facts": None,
    }
    return page_graph(**{**arguments, **overrides})


def _node(graph: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(
        node
        for node in graph["@graph"]
        if kind in (node["@type"] if isinstance(node["@type"], list) else [node["@type"]])
    )


# --- The graph itself ------------------------------------------------------------------


def test_a_card_with_an_address_is_a_local_business_with_its_categorys_subtype() -> None:
    facts = {
        "name": "Pensjonat Pod Lasem",
        "business_type": "LodgingBusiness",
        "telephone": "+48 600 100 200",
        "email": "kontakt@podlasem.test",
        "street_address": "Leśna 4",
        "locality": "Zakopane",
        "region": "małopolskie",
        "country": "PL",
        "same_as": ["https://facebook.com/podlasem"],
    }

    node = organization_node(origin=ORIGIN, site_name="Pod Lasem", facts=facts)

    assert node == {
        "@type": ["LocalBusiness", "LodgingBusiness"],
        "@id": f"{ORIGIN}/#organization",
        "name": "Pensjonat Pod Lasem",
        "url": f"{ORIGIN}/",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "Leśna 4",
            "addressLocality": "Zakopane",
            "addressRegion": "małopolskie",
            "addressCountry": "PL",
        },
        "telephone": "+48 600 100 200",
        "email": "kontakt@podlasem.test",
        "sameAs": ["https://facebook.com/podlasem"],
    }
    # A category too wide to name a subtype: a plain local business.
    plain = organization_node(
        origin=ORIGIN, site_name="Pod Lasem", facts={**facts, "business_type": ""}
    )
    assert plain["@type"] == "LocalBusiness"


def test_without_an_address_the_company_is_an_organization_and_without_a_card_the_site() -> None:
    known = organization_node(
        origin=ORIGIN,
        site_name="Studio",
        facts={"name": "Studio Ewa", "business_type": "Store", "locality": "Kraków"},
    )
    assert known["@type"] == "Organization"
    assert known["name"] == "Studio Ewa"
    assert known["address"] == {"@type": "PostalAddress", "addressLocality": "Kraków"}

    assert organization_node(origin=ORIGIN, site_name="Studio", facts=None) == {
        "@type": "Organization",
        "@id": f"{ORIGIN}/#organization",
        "name": "Studio",
        "url": f"{ORIGIN}/",
    }


def test_every_node_points_at_the_one_company_and_the_one_site() -> None:
    graph = _page()

    page = _node(graph, "WebPage")
    assert page["@id"] == f"{ORIGIN}/oferta/#webpage"
    assert page["inLanguage"] == "pl"
    assert page["isPartOf"] == {"@id": f"{ORIGIN}/#website"}
    assert page["about"] == {"@id": f"{ORIGIN}/#organization"}
    assert _node(graph, "WebSite")["publisher"] == {"@id": f"{ORIGIN}/#organization"}
    trail = _node(graph, "BreadcrumbList")
    assert page["breadcrumb"] == {"@id": trail["@id"]}
    assert [
        (item["position"], item["name"], item["item"]) for item in trail["itemListElement"]
    ] == [
        (1, "Start", f"{ORIGIN}/"),
        (2, "Oferta", f"{ORIGIN}/oferta/"),
    ]
    assert len([node for node in graph["@graph"] if "Organization" in str(node["@type"])]) == 1


def test_a_page_with_questions_is_an_faq_page() -> None:
    blocks = [
        {"block_type": "core.hero", "data": {"title": "Oferta"}},
        {
            "block_type": "core.faq",
            "data": {
                "items": [
                    {"question": "Ile to trwa?", "answer": "Dwa tygodnie."},
                    {"question": " ", "answer": "bez pytania"},
                ]
            },
        },
    ]

    page = _node(_page(blocks=blocks), "WebPage")

    assert page["@type"] == ["WebPage", "FAQPage"]
    assert page["mainEntity"] == [
        {
            "@type": "Question",
            "name": "Ile to trwa?",
            "acceptedAnswer": {"@type": "Answer", "text": "Dwa tygodnie."},
        }
    ]
    assert _node(_page(), "WebPage")["@type"] == "WebPage"


def test_an_article_names_its_author_its_dates_and_the_company_as_publisher() -> None:
    article = {
        "author_name": "Ewa Nowak",
        "published_at": "2026-09-01T08:00:00+00:00",
        "updated_at": "2026-09-20T10:30:00+00:00",
        "tags": [{"slug": "porady", "name": "Porady"}],
    }
    image = {"url": f"{ORIGIN}/media/1", "alt": "Salon"}

    posting = _node(_page(article=article, image=image), "BlogPosting")

    assert posting["headline"] == "Oferta"
    assert posting["author"] == {"@type": "Person", "name": "Ewa Nowak"}
    assert posting["publisher"] == {"@id": f"{ORIGIN}/#organization"}
    assert posting["datePublished"] == "2026-09-01T08:00:00+00:00"
    assert posting["dateModified"] == "2026-09-20T10:30:00+00:00"
    assert posting["mainEntityOfPage"] == {"@id": f"{ORIGIN}/oferta/#webpage"}
    assert posting["image"] == f"{ORIGIN}/media/1"
    assert posting["keywords"] == ["Porady"]
    # Nobody signed it: the company wrote it.
    unsigned = _node(_page(article={**article, "author_name": ""}), "BlogPosting")
    assert unsigned["author"] == {"@id": f"{ORIGIN}/#organization"}


# --- On a published site ---------------------------------------------------------------


def test_every_language_of_a_site_names_the_same_company_with_the_same_facts() -> None:
    client, site_id, _home, _offer, host = _two_language_site("graph-one-company")
    _card(
        site_id,
        contact_phone="+48 600 100 200",
        contact_address="Długa 5",
        city_slug="krakow",
        category="handel",
        links=[{"label": "Facebook", "url": "https://facebook.com/studio"}],
    )
    _publish(client, site_id, "with-card")

    polish = _graph(host, "/oferta/")
    english = _graph(host, "/en/oferta-en/")

    company = polish["LocalBusiness"]
    assert company == english["LocalBusiness"]
    assert company["@id"] == f"https://{host}/#organization"
    # „handel” is a shop in the core's dictionary; a product brings its own categories.
    shop = categories(settings.DEFAULT_ORGANIZATION_TYPE).get("handel")
    assert company["@type"] == (["LocalBusiness", "Store"] if shop else "LocalBusiness")
    assert company["name"] == "Studio Projektowe Ewa"
    assert company["telephone"] == "+48 600 100 200"
    assert company["address"]["streetAddress"] == "Długa 5"
    assert company["address"]["addressLocality"] == "Kraków"
    assert company["address"]["addressCountry"] == "PL"
    assert company["sameAs"] == ["https://facebook.com/studio"]
    assert polish["WebSite"]["@id"] == english["WebSite"]["@id"] == f"https://{host}/#website"
    # The page is its own node per language, in its language.
    assert polish["WebPage"]["@id"] == f"https://{host}/oferta/#webpage"
    assert english["WebPage"]["@id"] == f"https://{host}/en/oferta-en/#webpage"
    assert (polish["WebPage"]["inLanguage"], english["WebPage"]["inLanguage"]) == ("pl", "en")
    assert english["WebPage"]["name"] == _get(host, "/en/oferta-en/").json()["title"]


def test_the_facts_are_the_publications_and_change_with_the_next_one() -> None:
    client, site_id, _home, _offer, host = _two_language_site("graph-frozen")
    # Published before the company had a card: known by the site's name.
    first = Site.all_objects.get(pk=site_id).current_publication_id
    before = _graph(host, "/")["Organization"]
    assert before["name"] == Site.all_objects.get(pk=site_id).name
    assert "telephone" not in before

    card = _card(site_id, contact_phone="+48 600 100 200")
    assert "telephone" not in _graph(host, "/")["Organization"]

    _publish(client, site_id, "second")
    assert _graph(host, "/")["Organization"]["telephone"] == "+48 600 100 200"
    assert _graph(host, "/")["Organization"]["name"] == "Studio Projektowe Ewa"

    # The card changes; the published site says what it said when published.
    card.contact_phone = "+48 700 700 700"
    card.save()
    assert _graph(host, "/")["Organization"]["telephone"] == "+48 600 100 200"

    # Going back to a publication from before the facts were frozen.
    back = rollback_site_request(client, site_id, str(first), idempotency_key="graph-back")
    assert back.status_code == 201, back.content
    old = _graph(host, "/")["Organization"]
    assert (
        "organization"
        not in Publication.all_objects.get(
            pk=Site.all_objects.get(pk=site_id).current_publication_id
        ).snapshot
    )
    assert old == before


def test_an_articles_dates_are_the_ones_the_sitemap_and_the_head_carry() -> None:
    blog = Blog("graph-article")
    _translate_entry(blog.client, blog.polish, "in-english", "In English")
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        listing = APIClient().get(
            "/api/v1/public/site/", {"path": "/en/blog/in-english/"}, HTTP_HOST=blog.host
        )
    assert listing.status_code == 200, listing.content
    payload = listing.json()

    posting = next(
        node for node in payload["structured_data"]["@graph"] if node["@type"] == "BlogPosting"
    )

    assert posting["inLanguage"] == "en"
    assert posting["headline"] == "In English"
    # The same values the visitor's byline and `article:modified_time` read.
    assert posting["dateModified"] == payload["article"]["updated_at"]
    assert posting["datePublished"] == payload["article"]["published_at"]
    lastmod = re.search(
        r"<lastmod>([^<]+)</lastmod>", _url(_sitemap(blog.host), blog.host, "/en/blog/in-english/")
    )
    assert lastmod is not None
    assert posting["dateModified"].startswith(lastmod.group(1))
    # The company behind the article is the site's one company.
    assert posting["publisher"] == {"@id": f"https://{blog.host}/#organization"}


def test_the_card_states_the_facts_and_nothing_without_a_card() -> None:
    from saas_core.modules.core.organizations.api import organization_facts

    _client, site_id, _home, _offer, _host = _two_language_site("graph-facts")
    organization_id = Site.all_objects.get(pk=site_id).organization_id
    assert organization_facts(organization_id) is None

    _card(site_id, contact_email="biuro@studio.test", city_slug="krakow", category="inne")
    facts = organization_facts(organization_id)

    assert facts is not None
    assert facts.as_snapshot() == {
        "name": "Studio Projektowe Ewa",
        "email": "biuro@studio.test",
        "locality": "Kraków",
        "region": "małopolskie",
        "country": "PL",
    }
