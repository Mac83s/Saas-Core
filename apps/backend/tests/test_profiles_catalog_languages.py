"""The catalogue per language (TL20a): the row knows where a card speaks.

A card is in another language only whole; the catalogue row copies which
languages those are and the headline in each, so the listing and the sitemap
answer without opening a tenant. The copy follows translations, card edits and
the company's languages.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid7

import pytest
from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationStatus,
    Role,
)
from saas_core.modules.core.organizations.public_locales import change_public_locales
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)
from saas_core.modules.shared.profiles.catalog import publish_profile
from saas_core.modules.shared.profiles.catalog_contract import categories
from saas_core.modules.shared.profiles.models import CatalogEntry, PublicProfile
from saas_core.modules.shared.profiles.services import (
    organization_profile,
    save_translation,
    update_profile,
)
from saas_core.modules.shared.profiles.translation_source import link_key

pytestmark = pytest.mark.django_db

CATALOG_URL = "/api/v1/public/catalog/"


@pytest.fixture(autouse=True)
def german_on_the_platform() -> Iterator[None]:
    cache.clear()
    with override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de")):
        yield


@contextmanager
def _as(context: TenantContext) -> Iterator[None]:
    with transaction.atomic():
        set_local_organization_id(context.organization_id)
        with activate_tenant_context(context):
            yield


class Company:
    """A company with a published card in Mrągowo: headline, bio, one link."""

    def __init__(self, name: str = "Salon Języki", locales: tuple[str, ...] = ("pl", "de")):
        user = User.objects.create_user(email=f"jezyki-{uuid7()}@example.test")
        user.status = UserStatus.ACTIVE
        user.save()
        self.organization = Organization.objects.create(
            name=name,
            slug=f"jezyki-{uuid7().hex[-12:]}",
            status=OrganizationStatus.ACTIVE,
            public_locales=list(locales),
        )
        EntitlementSnapshot.all_objects.create(
            organization=self.organization,
            subscription_state=SubscriptionState.ACTIVE,
            access_mode=AccessMode.FULL,
            features={"profiles.enabled": True},
            sources={"profiles.enabled": {"kind": "plan"}},
        )
        membership = Membership.objects.create(
            organization=self.organization,
            user=user,
            role=Role.objects.get(key="owner", organization=None, organization_type=""),
        )
        self.context = context_from_membership(membership)
        with _as(self.context):
            profile = organization_profile()
            profile = update_profile(
                profile.id,
                expected_version=profile.version,
                headline="Fryzjer w centrum",
                bio="Strzyżemy od 1990 roku.",
                links=[{"label": "Cennik", "url": f"https://example.test/{uuid7().hex}"}],
                city_slug="mragowo",
                category=next(iter(categories(settings.DEFAULT_ORGANIZATION_TYPE))),
            )
            publish_profile()
        self.card: UUID = profile.id

    @property
    def entry(self) -> CatalogEntry:
        return CatalogEntry.all_objects.get(profile_id=self.card)

    def _version(self, locale: str) -> int:
        with _as(self.context):
            row = (
                PublicProfile.all_objects.get(pk=self.card)
                .translations.filter(locale=locale)
                .first()
            )
        return row.version if row is not None else 0

    def translate(self, locale: str = "de", **values: Any) -> None:
        with _as(self.context):
            save_translation(
                self.card, locale=locale, expected_version=self._version(locale), **values
            )

    def translate_whole(self, locale: str = "de") -> None:
        link = PublicProfile.all_objects.get(pk=self.card).links[0]
        self.translate(
            locale,
            headline="Friseur im Zentrum",
            bio="Wir schneiden seit 1990.",
            link_labels={link_key(link["url"]): "Preise"},
        )

    def languages(self, locales: list[str]) -> None:
        with _as(self.context):
            current = Organization.objects.get(pk=self.organization.pk)
            change_public_locales(
                locales=locales,
                expected_version=current.public_locales_version,
                idempotency_key=str(uuid7()),
            )


def test_publication_and_a_whole_translation_put_the_language_on_the_row() -> None:
    company = Company()
    assert (company.entry.source_locale, company.entry.translated_locales) == ("pl", [])

    company.translate(headline="Friseur im Zentrum")
    # Half a card is no German card.
    assert company.entry.translated_locales == []

    company.translate_whole()
    assert company.entry.translated_locales == ["de"]
    assert company.entry.headline_by_locale == {"de": "Friseur im Zentrum"}


def test_a_new_text_on_the_card_takes_the_language_off_until_it_is_translated() -> None:
    company = Company()
    company.translate_whole()
    links = list(PublicProfile.all_objects.get(pk=company.card).links)
    with _as(company.context):
        profile = PublicProfile.all_objects.get(pk=company.card)
        update_profile(
            company.card,
            expected_version=profile.version,
            links=[*links, {"label": "Galeria", "url": "https://example.test/galeria"}],
        )
    assert company.entry.translated_locales == []

    company.translate(link_labels={link_key("https://example.test/galeria"): "Galerie"})
    assert company.entry.translated_locales == ["de"]


def test_a_language_the_company_switches_off_never_shows_and_returns_when_back_on() -> None:
    company = Company()
    company.translate_whole()
    entry = company.entry
    detail = f"{CATALOG_URL}{entry.city_slug}/{entry.slug}/"

    company.languages(["pl"])

    assert company.entry.translated_locales == []
    cache.clear()
    assert APIClient().get(detail, {"locale": "de"}).data["locale"] == "pl"
    listing = APIClient().get(CATALOG_URL, {"city": "mragowo", "locale": "de"}).data
    assert [item["headline"] for item in listing["items"]] == ["Fryzjer w centrum"]
    assert listing["items"][0]["translated_locales"] == []
    sitemap = APIClient().get(f"{CATALOG_URL}sitemap/").data
    assert [item["translated_locales"] for item in sitemap["items"]] == [[]]

    company.languages(["pl", "de"])

    assert company.entry.translated_locales == ["de"]
    cache.clear()
    assert APIClient().get(detail, {"locale": "de"}).data["locale"] == "de"


def test_the_listing_speaks_the_asked_language_from_the_row_alone() -> None:
    german = Company("Salon Niemiecki")
    german.translate_whole()
    Company("Salon Polski")

    with CaptureQueriesContext(connection) as captured:
        listing = APIClient().get(CATALOG_URL, {"city": "mragowo", "locale": "de"})

    assert listing.status_code == 200
    by_name = {item["display_name"]: item for item in listing.data["items"]}
    assert (by_name["Salon Niemiecki"]["headline"], by_name["Salon Niemiecki"]["locale"]) == (
        "Friseur im Zentrum",
        "de",
    )
    assert (by_name["Salon Polski"]["headline"], by_name["Salon Polski"]["locale"]) == (
        "Fryzjer w centrum",
        "pl",
    )
    assert listing.data["locale_has_entries"] is True
    # Not one tenant table: the languages are the row's copy (ADR-053 §4).
    statements = " ".join(query["sql"] for query in captured.captured_queries)
    assert "profiles_publicprofile" not in statements
    assert "app.organization_id" not in statements

    english = APIClient().get(CATALOG_URL, {"city": "mragowo", "locale": "en"}).data
    assert english["locale_has_entries"] is False
    assert APIClient().get(CATALOG_URL, {"locale": "xx"}).data["locale_has_entries"] is None


def test_the_sitemap_feed_lists_every_address_with_its_languages() -> None:
    german = Company("Salon Niemiecki")
    german.translate_whole()
    Company("Salon Polski")

    with CaptureQueriesContext(connection) as captured:
        page = APIClient().get(f"{CATALOG_URL}sitemap/")

    assert page.status_code == 200
    assert page.data["total"] == 2
    languages = {item["slug"]: item["translated_locales"] for item in page.data["items"]}
    assert languages == {
        german.entry.slug: ["de"],
        CatalogEntry.all_objects.exclude(profile_id=german.card).get().slug: [],
    }
    assert {item["source_locale"] for item in page.data["items"]} == {"pl"}
    statements = " ".join(query["sql"] for query in captured.captured_queries)
    assert "profiles_publicprofile" not in statements
    assert APIClient().get(f"{CATALOG_URL}sitemap/", {"page": 2}).data["items"] == []


def test_the_backfill_recomputes_every_row_and_twice_is_the_same() -> None:
    from importlib import import_module

    fill = import_module(
        "saas_core.modules.shared.profiles.migrations.0010_catalog_entry_languages_fill"
    ).fill_languages
    german = Company("Salon Niemiecki")
    german.translate_whole()
    polish = Company("Salon Polski")
    CatalogEntry.all_objects.update(
        source_locale="en", translated_locales=["en"], headline_by_locale={"en": "x"}
    )
    editor = SimpleNamespace(connection=connection)

    fill(apps, editor)
    first = list(
        CatalogEntry.all_objects.order_by("id").values_list(
            "source_locale", "translated_locales", "headline_by_locale"
        )
    )
    fill(apps, editor)

    assert first == list(
        CatalogEntry.all_objects.order_by("id").values_list(
            "source_locale", "translated_locales", "headline_by_locale"
        )
    )
    assert (german.entry.translated_locales, german.entry.headline_by_locale) == (
        ["de"],
        {"de": "Friseur im Zentrum"},
    )
    assert (polish.entry.source_locale, polish.entry.translated_locales) == ("pl", [])


def test_the_dictionary_names_the_languages_some_card_is_whole_in() -> None:
    Company("Salon Polski")
    assert APIClient().get(f"{CATALOG_URL}dictionary/").data["locales"] == ["pl"]

    german = Company("Salon Niemiecki")
    german.translate_whole()

    assert APIClient().get(f"{CATALOG_URL}dictionary/").data["locales"] == ["pl", "de"]
