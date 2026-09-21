"""The public business-card catalogue (ADR-053).

What is worth a test here is what a later change could quietly undo:

- the company profile exists from the first read, but is not published by that;
- city and category come from the dictionary, and junk is refused rather than
  slugified into an address nobody chose;
- the catalogue row exists exactly while the profile is published;
- the public read is anonymous, touches only `profiles_catalogentry` without a
  tenant, and **sets the tenant before reading the profile itself**. The test
  database connects as the table owner and therefore bypasses row-level
  security, so the ordering assertion — not a green read — is what stands in
  for isolation here (AGENTS.md).
"""

from __future__ import annotations

from typing import Any

import pytest
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationStatus,
    Role,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)
from saas_core.modules.shared.profiles.catalog_contract import categories
from saas_core.modules.shared.profiles.models import (
    CatalogEntry,
    ProfileSubjectKind,
    PublicProfile,
)

pytestmark = pytest.mark.django_db

PASSWORD = "Bezpieczne-Haslo-2026!"
PROFILE_URL = "/api/v1/profiles/organization/"
PUBLISH_URL = "/api/v1/profiles/organization/catalog/"
CATALOG_URL = "/api/v1/public/catalog/"


@pytest.fixture(autouse=True)
def clear_session_cache() -> None:
    cache.clear()


def catalog_client(
    *, slug: str, role_key: str = "owner", feature_enabled: bool = True
) -> tuple[APIClient, Organization, User]:
    user = User.objects.create_user(email=f"{slug}@example.test", password=PASSWORD)
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name=slug.replace("-", " ").title(), slug=slug, status=OrganizationStatus.ACTIVE
    )
    Membership.objects.create(
        organization=organization,
        user=user,
        role=Role.objects.get(key=role_key, organization=None, organization_type=""),
    )
    EntitlementSnapshot.all_objects.create(
        organization=organization,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={"profiles.enabled": feature_enabled, "sites.enabled": True},
        quotas={"sites.max": 3},
        sources={"profiles.enabled": {"kind": "plan"}},
    )
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf/").data["csrf_token"]
    assert (
        client.post(
            "/api/v1/auth/login/",
            {"email": user.email, "password": PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        ).status_code
        == 200
    )
    return client, organization, user


def _csrf(client: APIClient) -> str:
    return client.cookies["csrftoken"].value


def _fill(client: APIClient, profile: dict[str, Any], **values: Any) -> Any:
    payload = {
        "display_name": profile["display_name"],
        "city_slug": "mragowo",
        "category": next(iter(categories(settings.DEFAULT_ORGANIZATION_TYPE))),
        "expected_version": profile["version"],
        **values,
    }
    return client.put(
        f"/api/v1/profiles/{profile['id']}/",
        payload,
        format="json",
        HTTP_X_CSRFTOKEN=_csrf(client),
    )


def _ready(client: APIClient, **values: Any) -> dict[str, Any]:
    profile = client.get(PROFILE_URL).data["profile"]
    response = _fill(client, profile, **values)
    assert response.status_code == 200, response.data
    return dict(response.data)


def test_company_profile_appears_on_first_read_and_is_not_published_by_it() -> None:
    client, organization, _user = catalog_client(slug="wizytowka-lazy")
    assert not PublicProfile.all_objects.filter(organization=organization).exists()

    body = client.get(PROFILE_URL).data

    assert body["profile"]["display_name"] == organization.name
    assert body["profile"]["subject_kind"] == ProfileSubjectKind.ORGANIZATION
    assert body["catalog"]["published"] is False
    # A second read must not make a second profile; the partial unique index
    # would refuse it, and the endpoint has to be safe to poll.
    assert client.get(PROFILE_URL).data["profile"]["id"] == body["profile"]["id"]
    assert PublicProfile.all_objects.filter(organization=organization).count() == 1


def test_city_and_category_must_come_from_the_dictionary() -> None:
    client, _organization, _user = catalog_client(slug="wizytowka-slownik")
    profile = client.get(PROFILE_URL).data["profile"]

    bad_city = _fill(client, profile, city_slug="mragowo-centrum")
    assert bad_city.status_code == 400
    assert "city_slug" in bad_city.data["detail"]

    bad_category = _fill(client, profile, category="fryzjerstwo-meskie")
    assert bad_category.status_code == 400
    assert "category" in bad_category.data["detail"]


def test_publication_needs_a_place_and_puts_the_company_in_the_public_listing() -> None:
    client, organization, _user = catalog_client(slug="wizytowka-publikacja")
    profile = client.get(PROFILE_URL).data["profile"]

    incomplete = client.post(PUBLISH_URL, {}, format="json", HTTP_X_CSRFTOKEN=_csrf(client))
    assert incomplete.status_code == 409
    assert incomplete.data["code"] == "profile_not_publishable"

    _fill(client, profile, headline="Salon fryzjerski")
    published = client.post(PUBLISH_URL, {}, format="json", HTTP_X_CSRFTOKEN=_csrf(client))
    assert published.status_code == 200
    assert published.data["catalog"]["published"] is True
    assert published.data["catalog"]["path"] == "/katalog/mragowo/wizytowka-publikacja/"

    anonymous = APIClient()
    listing = anonymous.get(CATALOG_URL, {"city": "mragowo"})
    assert listing.status_code == 200
    assert [item["display_name"] for item in listing.data["items"]] == [organization.name]
    # No site yet, so the entry leads to the platform's own page.
    assert listing.data["items"][0]["is_external"] is False
    assert listing.data["items"][0]["url"] == "/katalog/mragowo/wizytowka-publikacja/"


def test_withdrawal_removes_the_row_rather_than_flagging_it() -> None:
    client, organization, _user = catalog_client(slug="wizytowka-wycofanie")
    _ready(client)
    client.post(PUBLISH_URL, {}, format="json", HTTP_X_CSRFTOKEN=_csrf(client))
    assert CatalogEntry.all_objects.filter(organization=organization).count() == 1

    withdrawn = client.delete(PUBLISH_URL, HTTP_X_CSRFTOKEN=_csrf(client))

    assert withdrawn.status_code == 204
    assert CatalogEntry.all_objects.filter(organization=organization).count() == 0
    assert APIClient().get(CATALOG_URL, {"city": "mragowo"}).data["total"] == 0
    assert client.get(PROFILE_URL).data["catalog"]["published"] is False


def test_people_never_reach_the_catalogue() -> None:
    """Not a filter — a person profile has no way into this table at all.

    That is the whole reason the catalogue is its own table rather than an
    opened `profiles_publicprofile` (ADR-053 §4).
    """
    client, organization, _user = catalog_client(slug="wizytowka-osoby")
    _ready(client)
    client.post(PUBLISH_URL, {}, format="json", HTTP_X_CSRFTOKEN=_csrf(client))
    person = client.post(
        "/api/v1/profiles/",
        {
            "subject_kind": ProfileSubjectKind.PERSON,
            "display_name": "Anna Kowalska",
            "contact_phone": "+48 600 100 200",
        },
        format="json",
        HTTP_X_CSRFTOKEN=_csrf(client),
    )
    assert person.status_code == 201

    listing = APIClient().get(CATALOG_URL, {"city": "mragowo"}).data

    assert [item["display_name"] for item in listing["items"]] == [organization.name]
    assert CatalogEntry.all_objects.filter(profile__subject_kind="person").count() == 0


def test_two_companies_of_one_name_in_one_town_get_distinct_addresses() -> None:
    first, _organization, _user = catalog_client(slug="salon-uroda")
    second, _other, _other_user = catalog_client(slug="salon-uroda-2")
    for client in (first, second):
        _ready(client, display_name="Salon Uroda")
        assert (
            client.post(PUBLISH_URL, {}, format="json", HTTP_X_CSRFTOKEN=_csrf(client)).status_code
            == 200
        )

    slugs = sorted(
        CatalogEntry.all_objects.filter(city_slug="mragowo").values_list("slug", flat=True)
    )

    assert slugs == ["salon-uroda", "salon-uroda-2"]


def test_republishing_keeps_the_address_a_renamed_company_already_earned() -> None:
    client, _organization, _user = catalog_client(slug="wizytowka-adres")
    _ready(client, display_name="Stara Nazwa")
    first = client.post(PUBLISH_URL, {}, format="json", HTTP_X_CSRFTOKEN=_csrf(client))
    assert first.data["catalog"]["slug"] == "stara-nazwa"

    profile = client.get(PROFILE_URL).data["profile"]
    _fill(client, profile, display_name="Nowa Nazwa")
    again = client.post(PUBLISH_URL, {}, format="json", HTTP_X_CSRFTOKEN=_csrf(client))

    assert again.data["catalog"]["slug"] == "stara-nazwa"
    assert again.data["profile"]["display_name"] == "Nowa Nazwa"


def test_the_catalogue_page_sets_the_tenant_before_reading_the_profile() -> None:
    """The ordering assertion AGENTS.md asks for: a green read proves nothing here.

    `profiles_catalogentry` is read with no tenant by design; everything after
    it must come after `SET LOCAL app.organization_id`.
    """
    client, _organization, _user = catalog_client(slug="wizytowka-kolejnosc")
    _ready(client, headline="Salon fryzjerski", contact_phone="+48 600 100 200")
    client.post(PUBLISH_URL, {}, format="json", HTTP_X_CSRFTOKEN=_csrf(client))

    with CaptureQueriesContext(connection) as captured:
        page = APIClient().get(f"{CATALOG_URL}mragowo/wizytowka-kolejnosc/")

    assert page.status_code == 200
    assert page.data["contact_phone"] == "+48 600 100 200"

    statements = [query["sql"] for query in captured.captured_queries]
    set_local = next(index for index, sql in enumerate(statements) if "app.organization_id" in sql)
    profile_read = next(
        index for index, sql in enumerate(statements) if "profiles_publicprofile" in sql
    )
    catalogue_read = next(
        index for index, sql in enumerate(statements) if "profiles_catalogentry" in sql
    )
    assert catalogue_read < set_local < profile_read


def test_an_unknown_address_is_not_found() -> None:
    response = APIClient().get(f"{CATALOG_URL}mragowo/nie-ma-takiej-firmy/")

    assert response.status_code == 404
    assert response.data["code"] == "catalog_entry_not_found"


def test_the_dictionary_is_served_for_the_search_form() -> None:
    body = APIClient().get(f"{CATALOG_URL}dictionary/").data

    assert {"slug": "mragowo", "name": "Mrągowo", "voivodeship": "warmińsko-mazurskie"} in body[
        "cities"
    ]
    expected = categories(settings.DEFAULT_ORGANIZATION_TYPE)
    assert expected, "The default organization type needs public catalogue categories"
    assert {c["key"]: c["labels"] for c in body["categories"]} == {
        key: category.label for key, category in expected.items()
    }


def test_publication_is_refused_without_the_feature() -> None:
    client, _organization, _user = catalog_client(slug="wizytowka-bez-cechy", feature_enabled=False)
    _ready(client)

    response = client.post(PUBLISH_URL, {}, format="json", HTTP_X_CSRFTOKEN=_csrf(client))

    assert response.status_code == 403
    assert response.data["code"] == "entitlement_required"
