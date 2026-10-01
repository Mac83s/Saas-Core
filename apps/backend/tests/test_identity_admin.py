"""The operator admin accepts only a panel session whose second factor was checked.

Before 2026-10-01 `/internal/admin/` had Django's password-only login, so a
staff password alone opened the editor of `User.is_staff` (ADR-023, ADR-059).
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.mfa import current_totp_code
from saas_core.modules.core.identity.models import User, UserStatus

pytestmark = pytest.mark.django_db

ADMIN_URL = "/internal/admin/"
ADMIN_LOGIN_URL = "/internal/admin/login/"
CSRF_URL = "/api/v1/auth/csrf/"
LOGIN_URL = "/api/v1/auth/login/"
MFA_LOGIN_URL = "/api/v1/auth/login/mfa/"
MFA_SETUP_URL = "/api/v1/auth/mfa/totp/setup/"
MFA_CONFIRM_URL = "/api/v1/auth/mfa/totp/confirm/"
LOGOUT_URL = "/api/v1/auth/logout/"
PASSWORD = "Bezpieczne-Haslo-Admin-2026!"


@pytest.fixture(autouse=True)
def clear_session_cache() -> None:
    cache.clear()


@pytest.fixture(autouse=True)
def plain_static_storage(settings) -> None:  # type: ignore[no-untyped-def]
    """Admin pages render `{% static %}`; the suite has no collected manifest."""
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


def active_user(email: str, *, staff: bool) -> User:
    user = User.objects.create_user(email=email, password=PASSWORD, is_staff=staff)
    user.status = UserStatus.ACTIVE
    user.save()
    return user


def csrf(client: APIClient) -> str:
    if "csrftoken" not in client.cookies:
        client.get(CSRF_URL)
    return client.cookies["csrftoken"].value


def login(client: APIClient, user: User) -> Any:
    client.get(CSRF_URL)
    return client.post(
        LOGIN_URL,
        {"email": user.email, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf(client),
    )


def enroll_totp(client: APIClient) -> str:
    setup = client.post(MFA_SETUP_URL, HTTP_X_CSRFTOKEN=csrf(client))
    assert setup.status_code == 200, setup.data
    secret = str(setup.data["secret"])
    confirmed = client.post(
        MFA_CONFIRM_URL,
        {"code": current_totp_code(secret)},
        format="json",
        HTTP_X_CSRFTOKEN=csrf(client),
    )
    assert confirmed.status_code == 200, confirmed.data
    return secret


def operator_after_enrolment(email: str = "operator@example.test") -> tuple[APIClient, str]:
    """A staff account's first sign-in: no session until the TOTP is confirmed."""
    user = active_user(email, staff=True)
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).data["code"] == "mfa_setup_required"
    return client, enroll_totp(client)


def test_the_admin_has_no_password_login_of_its_own() -> None:
    user = active_user("operator@example.test", staff=True)
    client = Client()

    shown = client.get(ADMIN_LOGIN_URL)
    submitted = client.post(ADMIN_LOGIN_URL, {"username": user.email, "password": PASSWORD})

    assert shown.status_code == 403
    assert submitted.status_code == 403
    assert "_auth_user_id" not in client.session
    assert client.get(ADMIN_URL).status_code == 302


def test_a_session_not_made_by_the_panel_is_logged_out_on_the_admin() -> None:
    user = active_user("operator@example.test", staff=True)
    client = Client()
    client.force_login(user)

    response = client.get(ADMIN_URL)

    assert response.status_code == 302
    assert response["Location"].startswith(ADMIN_LOGIN_URL)
    assert "_auth_user_id" not in client.session


def test_an_operator_enters_after_enrolment_and_after_an_mfa_login() -> None:
    client, secret = operator_after_enrolment()

    assert client.get(ADMIN_URL).status_code == 200
    assert client.get(ADMIN_LOGIN_URL).status_code == 302

    client.post(LOGOUT_URL, HTTP_X_CSRFTOKEN=csrf(client))
    user = User.objects.get(email="operator@example.test")
    again = APIClient(enforce_csrf_checks=True)
    assert login(again, user).status_code == 202
    assert again.get(ADMIN_URL).status_code == 302
    second_factor = again.post(
        MFA_LOGIN_URL,
        {"code": current_totp_code(secret, at=timezone.now().timestamp() + 30)},
        format="json",
        HTTP_X_CSRFTOKEN=csrf(again),
    )
    assert second_factor.status_code == 200, second_factor.data
    assert again.get(ADMIN_URL).status_code == 200


def test_a_session_that_began_without_mfa_stays_out_after_promotion() -> None:
    user = active_user("member@example.test", staff=False)
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 200
    enroll_totp(client)
    User.objects.filter(pk=user.pk).update(is_staff=True)

    response = client.get(ADMIN_URL)

    assert response.status_code == 302
    assert response["Location"].startswith(ADMIN_LOGIN_URL)


def test_a_member_with_mfa_is_not_an_operator() -> None:
    user = active_user("member@example.test", staff=False)
    enrolment = APIClient(enforce_csrf_checks=True)
    assert login(enrolment, user).status_code == 200
    secret = enroll_totp(enrolment)
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 202
    assert (
        client.post(
            MFA_LOGIN_URL,
            {"code": current_totp_code(secret, at=timezone.now().timestamp() + 30)},
            format="json",
            HTTP_X_CSRFTOKEN=csrf(client),
        ).status_code
        == 200
    )

    assert client.get(ADMIN_URL).status_code == 302
