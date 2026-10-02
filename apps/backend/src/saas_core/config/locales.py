"""The content languages this platform knows, read from the contract (ADR-071 pkt 2).

`packages/contracts/locales/registry.json` is the one list: the Node deployment
check validates profiles against it in CI, and settings read it here at start,
so a profile naming a language the registry does not know stops the process
with a readable message instead of failing on the first German page. A new
language is an entry in that file, reviewed guest strings and a release — not
a switch in a panel.

Deliberately without Django imports, so settings can call it while the app
registry is still empty.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOCALE_CODE_PATTERN = re.compile(r"^[a-z]{2}$")
_SCRIPTS = frozenset({"Latn", "Cyrl"})
_FIELDS = (
    "code",
    "nativeName",
    "englishName",
    "ogLocale",
    "searchCode",
    "script",
    "paginationSegment",
    "appLocale",
)


class LocaleRegistryError(Exception):
    """The registry is missing, unreadable or says something it may not."""


@dataclass(frozen=True, slots=True)
class RegisteredLocale:
    code: str
    native_name: str
    english_name: str
    og_locale: str
    search_code: str
    script: str
    pagination_segment: str
    #: A language of the panel and of e-mails to the team (ADR-071 pkt 1).
    app_locale: bool


def load_locale_registry(path: Path) -> dict[str, RegisteredLocale]:
    """The registry by code, in the order the file lists it."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LocaleRegistryError(
            f"Nie można odczytać rejestru języków {path} (LOCALE_REGISTRY_PATH)."
        ) from error
    entries = document.get("locales") if isinstance(document, dict) else None
    if (
        not isinstance(document, dict)
        or document.get("schemaVersion") != 1
        or not isinstance(entries, list)
        or not entries
    ):
        raise LocaleRegistryError(f"Rejestr języków {path} nie ma listy języków w wersji 1.")
    registry: dict[str, RegisteredLocale] = {}
    for entry in entries:
        locale = _entry(entry, path)
        if locale.code in registry:
            raise LocaleRegistryError(f"Rejestr języków {path}: powtórzony kod {locale.code}.")
        registry[locale.code] = locale
    return registry


def _entry(entry: Any, path: Path) -> RegisteredLocale:
    if not isinstance(entry, dict) or any(field not in entry for field in _FIELDS):
        raise LocaleRegistryError(f"Rejestr języków {path}: wpis bez wymaganych pól: {entry!r}.")
    code = entry["code"]
    if not isinstance(code, str) or LOCALE_CODE_PATTERN.fullmatch(code) is None:
        raise LocaleRegistryError(
            f"Rejestr języków {path}: kod {code!r} nie jest dwuliterowym kodem ISO 639-1."
        )
    if entry["script"] not in _SCRIPTS or not isinstance(entry["appLocale"], bool):
        raise LocaleRegistryError(f"Rejestr języków {path}: wpis {code} ma złe pismo albo flagę.")
    return RegisteredLocale(
        code=code,
        native_name=str(entry["nativeName"]),
        english_name=str(entry["englishName"]),
        og_locale=str(entry["ogLocale"]),
        search_code=str(entry["searchCode"]),
        script=str(entry["script"]),
        pagination_segment=str(entry["paginationSegment"]),
        app_locale=entry["appLocale"],
    )


def profile_locales_problem(
    supported: Any, default: Any, registry: dict[str, RegisteredLocale]
) -> str | None:
    """Why a profile's languages cannot start, or None when they can."""
    if not isinstance(supported, list) or not supported:
        return "supportedLocales musi być niepustą listą"
    unknown = [locale for locale in supported if locale not in registry]
    if unknown:
        return (
            f"języki {', '.join(map(str, unknown))} nie są w rejestrze "
            "packages/contracts/locales/registry.json"
        )
    if default not in supported:
        return "defaultLocale musi należeć do supportedLocales"
    return None
