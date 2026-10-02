"""Content languages are registry codes the company has turned on (ADR-071 pkt 3, 6, 20)."""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.db import IntegrityError, transaction

from saas_core.modules.core.organizations.locales import (
    LOCALE_NOT_ENABLED,
    LOCALE_NOT_IN_REGISTRY,
    clamp_content_locale,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.notifications.api import (
    TEMPLATES,
    EmailTemplate,
    register_email_template,
    resolve_template_locale,
)
from saas_core.modules.shared.notifications.templates import AUDIENCE_STAFF
from saas_core.modules.shared.sites.models import Site
from test_sites_api import create_site, csrf_value, sites_client
from test_sites_collections import create_collection

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    cache.clear()


@pytest.fixture(autouse=True)
def every_registered_language(settings) -> None:  # type: ignore[no-untyped-def]
    # A profile serving every registry language, like a product with de, es and ru.
    settings.SITES_SUPPORTED_LOCALES = ("pl", "en", "de", "es", "ru")


def company_with(locales: list[str], slug: str):  # type: ignore[no-untyped-def]
    client, organization, user = sites_client(slug=slug, role_key="owner")
    Organization.objects.filter(pk=organization.pk).update(public_locales=locales)
    return client, organization, user


def post_entry(client, collection_id: str, locale: str, key: str):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/sites/collections/{collection_id}/entries/",
        {"slug": f"wpis-{key}", "locale": locale, "title": "Wpis"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=f"entry-{key}",
    )


def test_a_company_with_german_writes_german_and_nothing_it_has_not_turned_on() -> None:
    client, _organization, _user = company_with(["pl", "de"], "firma-de")
    site_id = create_site(client).data["id"]
    collection_id = create_collection(client, site_id).data["id"]

    german = post_entry(client, collection_id, "de", "de")
    spanish = post_entry(client, collection_id, "es", "es")
    french = post_entry(client, collection_id, "fr", "fr")
    upper = post_entry(client, collection_id, "DE", "upper")

    assert german.status_code == 201, german.data
    assert german.data["locale"] == "de"
    assert spanish.status_code == 400
    assert spanish.data["errors"][0]["code"] == LOCALE_NOT_ENABLED
    assert french.status_code == 400
    assert french.data["errors"][0]["code"] == LOCALE_NOT_IN_REGISTRY
    assert upper.status_code == 400
    assert upper.data["errors"][0]["field"] == "locale"


def test_the_database_refuses_a_code_that_is_not_two_letters() -> None:
    client, _organization, _user = company_with(["pl", "de"], "firma-baza")
    site_id = create_site(client).data["id"]

    with pytest.raises(IntegrityError), transaction.atomic():
        Site.all_objects.filter(pk=site_id).update(default_locale="deu")


def test_a_site_starts_only_in_a_language_the_templates_are_written_in() -> None:
    client, _organization, _user = company_with(["pl", "de"], "firma-nasiona")

    response = client.post(
        "/api/v1/sites/",
        {"name": "Seite", "slug": "seite", "default_locale": "de"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="site-de",
    )

    assert response.status_code == 400
    assert response.data["errors"][0] == {
        "field": "default_locale",
        "code": "locale_not_seeded",
        "message": response.data["errors"][0]["message"],
    }


def test_a_visitors_language_is_clamped_to_the_companys_never_refused() -> None:
    organization = Organization(name="Salon", slug="salon-jezyk", public_locales=["de", "pl"])

    assert clamp_content_locale("pl", organization=organization) == "pl"
    assert clamp_content_locale("fr", organization=organization) == "de"
    assert clamp_content_locale(None, organization=organization) == "de"


def test_a_template_without_the_requested_language_goes_out_in_english_then_polish() -> None:
    confirmation = TEMPLATES[("booking.confirmation", 2)]

    assert resolve_template_locale(confirmation, "pl") == "pl"
    assert resolve_template_locale(confirmation, "de") == "en"
    polish_only = EmailTemplate(
        key="test.polish_only",
        version=1,
        category="required",
        subjects={"pl": "Temat"},
        bodies={"pl": "<p>Treść</p>"},
        allowed_context=frozenset(),
    )
    assert resolve_template_locale(polish_only, "de") == "pl"


def test_a_products_own_template_registers_as_before_and_is_for_staff() -> None:
    report = EmailTemplate(
        key="test.report_ready",
        version=1,
        category="required",
        subjects={"pl": "Raport gotowy", "en": "Report ready"},
        bodies={"pl": "<p>{name}</p>", "en": "<p>{name}</p>"},
        allowed_context=frozenset({"name"}),
    )

    register_email_template(report)
    register_email_template(report)

    assert TEMPLATES[("test.report_ready", 1)].audience == AUDIENCE_STAFF
    assert TEMPLATES[("booking.confirmation", 2)].audience == "customer"
