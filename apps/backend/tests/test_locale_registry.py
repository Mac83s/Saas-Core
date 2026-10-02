"""The content-language registry the process starts from (ADR-071 pkt 2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.conf import settings

from saas_core.config.locales import (
    LocaleRegistryError,
    load_locale_registry,
    profile_locales_problem,
)

REGISTRY = Path(settings.LOCALE_REGISTRY_PATH)


def test_the_registry_lists_the_first_five_languages_and_the_panel_two() -> None:
    registry = load_locale_registry(REGISTRY)

    assert list(registry) == ["pl", "en", "de", "es", "ru"]
    assert settings.APP_LOCALES == ("pl", "en")
    assert registry["ru"].script == "Cyrl"
    assert registry["de"].pagination_segment == "seite"


def test_a_missing_registry_stops_the_start_with_the_variable_to_fix(tmp_path: Path) -> None:
    with pytest.raises(LocaleRegistryError, match="LOCALE_REGISTRY_PATH"):
        load_locale_registry(tmp_path / "registry.json")


@pytest.mark.parametrize("code", ["deu", "DE", "pl-PL", ""])
def test_a_code_that_is_not_two_lowercase_letters_is_refused(tmp_path: Path, code: str) -> None:
    document = json.loads(REGISTRY.read_text(encoding="utf-8"))
    document["locales"][0]["code"] = code
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(LocaleRegistryError, match="ISO 639-1"):
        load_locale_registry(path)


def test_a_repeated_code_is_refused(tmp_path: Path) -> None:
    document = json.loads(REGISTRY.read_text(encoding="utf-8"))
    document["locales"].append(dict(document["locales"][0]))
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(LocaleRegistryError, match="powtórzony"):
        load_locale_registry(path)


def test_a_profile_may_name_any_registered_language_and_nothing_else() -> None:
    registry = load_locale_registry(REGISTRY)

    assert profile_locales_problem(["pl", "en", "de", "es", "ru"], "pl", registry) is None
    assert "cz" in str(profile_locales_problem(["pl", "cz"], "pl", registry))
    assert "defaultLocale" in str(profile_locales_problem(["pl", "de"], "en", registry))
    assert profile_locales_problem([], "pl", registry) is not None
