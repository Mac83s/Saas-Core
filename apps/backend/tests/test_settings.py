import json
import logging
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from saas_core.config.settings.base import secret_setting
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
