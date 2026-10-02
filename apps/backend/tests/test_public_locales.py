"""A company's content languages: never empty, codes only, set on every path (ADR-071 pkt 4)."""

from __future__ import annotations

import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.platform_workspace import ensure_platform_workspace

pytestmark = pytest.mark.django_db

PASSWORD = "Bezpieczne-Haslo-2026!"
CSRF_URL = "/api/v1/auth/csrf/"
LOGIN_URL = "/api/v1/auth/login/"
ORGANIZATIONS_URL = "/api/v1/organizations/"


@pytest.fixture(autouse=True)
def clear_session_cache() -> None:
    cache.clear()


def signed_in_client() -> APIClient:
    user = User.objects.create_user(email="owner@example.com", password=PASSWORD)
    user.status = UserStatus.ACTIVE
    user.save()
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get(CSRF_URL).data["csrf_token"]
    response = client.post(
        LOGIN_URL,
        {"email": user.email, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 200
    return client


def test_a_new_company_speaks_the_profiles_first_language() -> None:
    client = signed_in_client()

    response = client.post(
        ORGANIZATIONS_URL,
        {
            "name": "Salon",
            "slug": "salon",
            "organization_type": settings.DEFAULT_ORGANIZATION_TYPE,
            "workspace_kind": "business",
            # The panel in English does not make the customers English.
            "default_locale": "en",
            "timezone": "Europe/Warsaw",
            "currency": "PLN",
        },
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )

    assert response.status_code == 201
    organization = Organization.objects.get(slug="salon")
    assert organization.default_locale == "en"
    assert organization.public_locales == [settings.SITES_DEFAULT_LOCALE]


def test_the_publisher_speaks_every_language_of_the_profile_and_a_panel_language() -> None:
    workspace, _ = ensure_platform_workspace()

    assert workspace.public_locales == list(settings.SITES_SUPPORTED_LOCALES)
    assert workspace.default_locale in settings.APP_LOCALES


@pytest.mark.parametrize("locales", [[], ["deu"], ["PL"], ["pl", "e"]])
def test_the_database_refuses_an_empty_list_or_a_code_of_the_wrong_shape(
    locales: list[str],
) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        Organization.objects.create(name="X", slug="x-locales", public_locales=locales)


@pytest.mark.parametrize("locales", [["pl", "pl"], ["pl", "xx"]])
def test_validation_refuses_repeated_or_unregistered_languages(locales: list[str]) -> None:
    organization = Organization(name="X", slug="x-locales", public_locales=locales)

    with pytest.raises(ValidationError) as error:
        organization.full_clean(validate_unique=False)

    assert "public_locales" in error.value.message_dict


def test_a_registered_language_beyond_pl_and_en_is_accepted() -> None:
    organization = Organization.objects.create(
        name="Hotel", slug="hotel-de", public_locales=["pl", "de", "ru"]
    )

    organization.full_clean(validate_unique=False)
    organization.refresh_from_db()
    assert organization.public_locales == ["pl", "de", "ru"]
