import json
import logging
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from saas_core.config.settings.base import (
    _deployment_billing_plan_keys,
    _validate_billing_provider,
    secret_setting,
)
from saas_core.observability import JsonFormatter, correlation_id


def test_secret_setting_reads_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_text("wartosc-sekretna\n", encoding="utf-8")
    monkeypatch.delenv("EXAMPLE_SECRET", raising=False)
    monkeypatch.setenv("EXAMPLE_SECRET_FILE", str(secret_file))

    assert secret_setting("EXAMPLE_SECRET") == "wartosc-sekretna"


def test_secret_setting_rejects_ambiguous_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_text("plik", encoding="utf-8")
    monkeypatch.setenv("EXAMPLE_SECRET", "env")
    monkeypatch.setenv("EXAMPLE_SECRET_FILE", str(secret_file))

    with pytest.raises(ImproperlyConfigured, match="nie oba"):
        secret_setting("EXAMPLE_SECRET")


def test_secret_setting_hides_file_system_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing_file = tmp_path / "wartosc-nie-trafia-do-komunikatu"
    monkeypatch.delenv("EXAMPLE_SECRET", raising=False)
    monkeypatch.setenv("EXAMPLE_SECRET_FILE", str(missing_file))

    with pytest.raises(ImproperlyConfigured, match="EXAMPLE_SECRET_FILE") as error:
        secret_setting("EXAMPLE_SECRET")

    assert str(missing_file) not in str(error.value)


def test_deployment_billing_plan_keys_follow_enabled_module() -> None:
    assert _deployment_billing_plan_keys({}, ["core.identity"]) == ()
    assert _deployment_billing_plan_keys(
        {"billing": {"planKeys": ["profile", "starter", "pro"]}},
        ["core.identity", "shared.billing"],
    ) == ("profile", "starter", "pro")
    # Produkt z dwoma typami organizacji sprzedaje więcej niż trzy plany.
    assert (
        len(
            _deployment_billing_plan_keys(
                {"billing": {"planKeys": ["profile", "starter", "pro", "farm_free", "farm_plus"]}},
                ["shared.billing"],
            )
        )
        == 5
    )


@pytest.mark.parametrize(
    "billing",
    [
        None,
        {"planKeys": []},
        {"planKeys": ["profile", "starter", "profile"]},
        {"planKeys": ["a", "b", "c", "d", "e", "f", "g"]},
    ],
)
def test_deployment_billing_plan_keys_reject_invalid_catalog(billing: object) -> None:
    profile = {} if billing is None else {"billing": billing}
    with pytest.raises(ImproperlyConfigured, match="billing.planKeys"):
        _deployment_billing_plan_keys(profile, ["shared.billing"])


@pytest.mark.parametrize("provider", ["", "fake", "STRIPE"])
def test_billing_provider_rejects_unknown_values(provider: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="BILLING_PROVIDER"):
        _validate_billing_provider(provider, app_env="test", stripe_livemode=False)


def test_simulated_billing_provider_is_allowed_only_outside_live_production() -> None:
    assert (
        _validate_billing_provider("simulated", app_env="test", stripe_livemode=False)
        == "simulated"
    )
    assert (
        _validate_billing_provider("simulated", app_env="staging", stripe_livemode=False)
        == "simulated"
    )
    with pytest.raises(ImproperlyConfigured, match="local, test albo staging"):
        _validate_billing_provider("simulated", app_env="production", stripe_livemode=False)
    with pytest.raises(ImproperlyConfigured, match="STRIPE_LIVEMODE"):
        _validate_billing_provider("simulated", app_env="staging", stripe_livemode=True)


def test_json_formatter_uses_context_and_allowlisted_fields() -> None:
    formatter = JsonFormatter()
    token = correlation_id.set("019febc2-7085-7716-b17d-cc2e4c3ec07c")
    try:
        record = logging.LogRecord(
            name="saas_core.http",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="request_completed",
            args=(),
            exc_info=None,
        )
        record.http_method = "GET"
        record.http_path = "/api/v1/example/"
        record.password = "nie-loguj"
        payload = json.loads(formatter.format(record))
    finally:
        correlation_id.reset(token)

    assert payload["correlation_id"] == "019febc2-7085-7716-b17d-cc2e4c3ec07c"
    assert payload["http_method"] == "GET"
    assert payload["http_path"] == "/api/v1/example/"
    assert "password" not in payload


def test_a_local_stack_served_over_https_hands_out_secure_cookies_and_hsts() -> None:
    """The dev VPS runs as APP_ENV=local behind https: what follows the name
    is only the redirect (found 03.10: its session cookie went out without
    Secure and without HSTS)."""
    from saas_core.config.settings.base import local_transport_security  # noqa: PLC0415

    assert local_transport_security("http", 3600) == {
        "SECURE_SSL_REDIRECT": False,
        "SECURE_HSTS_SECONDS": 0,
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": False,
        "SESSION_COOKIE_SECURE": False,
        "CSRF_COOKIE_SECURE": False,
    }
    assert local_transport_security("https", 3600) == {
        "SECURE_SSL_REDIRECT": False,
        "SECURE_HSTS_SECONDS": 3600,
        # A customer's own domain reaches the same backend: its other
        # subdomains are not the platform's to force onto https.
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": False,
        "SESSION_COOKIE_SECURE": True,
        "CSRF_COOKIE_SECURE": True,
    }


@pytest.mark.django_db
@pytest.mark.parametrize(("scheme", "secure"), [("http", False), ("https", True)])
def test_the_cookies_and_the_hsts_header_follow_the_scheme_the_stack_is_served_over(
    settings, scheme: str, secure: bool
) -> None:  # type: ignore[no-untyped-def]
    from django.test import Client  # noqa: PLC0415

    from saas_core.config.settings.base import local_transport_security  # noqa: PLC0415
    from saas_core.modules.core.identity.models import User, UserStatus  # noqa: PLC0415

    for name, value in local_transport_security(scheme, 3600).items():
        setattr(settings, name, value)
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.CSRF_TRUSTED_ORIGINS = ["https://testserver"]
    user = User.objects.create_user(email="ciastka@example.test", password="Bezpieczne-Haslo-2026!")
    user.status = UserStatus.ACTIVE
    user.save()
    client = Client(enforce_csrf_checks=True)
    forwarded = {"HTTP_X_FORWARDED_PROTO": scheme}

    token = client.get("/api/v1/auth/csrf/", **forwarded)
    login = client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": "Bezpieczne-Haslo-2026!"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        HTTP_REFERER="https://testserver/" if secure else "http://testserver/",
        **forwarded,
    )

    assert login.status_code == 200, login.content
    assert bool(client.cookies["csrftoken"]["secure"]) is secure
    assert bool(client.cookies[settings.SESSION_COOKIE_NAME]["secure"]) is secure
    assert ("Strict-Transport-Security" in token.headers) is secure
    assert "includeSubDomains" not in token.headers.get("Strict-Transport-Security", "")
    # The redirect stays off in both shapes: internal http hops cannot take it.
    assert client.get("/api/v1/health/live/").status_code == 200
