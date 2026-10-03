"""The platform's own values of the settings registry (class A; platform
settings plan, phase 1, S-T1/S-T2/S-T7; ADR-078 pkt 16).

A key whose `scopes` include `platform` may get a value from an operator:
an append-only `PlatformSettingEntry` with who and why, read through one
cached map for every process — a change bumps a version the cache is keyed
by, so the next read anywhere sees it. Below it the deployment's `.env`
(`platform_env`) and the code's default; above it, for a company key, the
company's own choice. Who may change a key is its `operator_level`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.cache import cache
from django.db import transaction
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.identity.operators import operator_level

from .models import PlatformSettingEntry
from .settings_registry import SettingSpec, check_value, setting_spec

_VERSION_KEY = "organizations:platform-settings:version"
_VALUES_KEY = "organizations:platform-settings:values:{}"
#: The map lives this long in the cache even when nothing changes it.
_CACHE_SECONDS = 600


@dataclass(frozen=True, slots=True)
class PlatformValue:
    key: str
    #: In force now and where it comes from: `platform` (an operator),
    #: `deployment` (`.env`) or `code`.
    value: Any
    source: str
    operator_level: int


class UnknownPlatformSetting(ValidationError):
    pass


def _version() -> int:
    version = cache.get(_VERSION_KEY)
    if version is None:
        cache.add(_VERSION_KEY, 1, None)
        version = cache.get(_VERSION_KEY, 1)
    return int(version)


def platform_overrides() -> dict[str, Any]:
    """{key: value} the operators set, the newest entry of each key; a key
    given back to the default is absent."""
    cache_key = _VALUES_KEY.format(_version())
    values = cache.get(cache_key)
    if values is None:
        values = {}
        for entry in PlatformSettingEntry.objects.order_by("key", "-created_at", "-id").distinct(
            "key"
        ):
            if entry.value is not None:
                values[entry.key] = entry.value
        cache.set(cache_key, values, _CACHE_SECONDS)
    return dict(values)


def platform_spec(key: str) -> SettingSpec:
    try:
        spec = setting_spec(key)
    except KeyError:
        spec = None
    if spec is None or "platform" not in spec.scopes:
        raise UnknownPlatformSetting(
            {"key": [f"Nie ma ustawienia platformy {key}."]}, code="unknown_setting"
        )
    return spec


def platform_setting(key: str) -> Any:
    """The value in force for the platform — what a module reads for a key
    only the platform sets."""
    return read_platform_setting(key).value


def read_platform_setting(key: str) -> PlatformValue:
    from django.conf import settings  # noqa: PLC0415

    spec = platform_spec(key)
    chosen = platform_overrides().get(key)
    if chosen is not None:
        return PlatformValue(key, chosen, "platform", spec.operator_level)
    if spec.platform_env is not None and getattr(settings, spec.platform_env, None) is not None:
        return PlatformValue(
            key, getattr(settings, spec.platform_env), "deployment", spec.operator_level
        )
    return PlatformValue(key, spec.default, "code", spec.operator_level)


@transaction.atomic
def change_platform_setting(
    key: str, value: Any, *, operator: User, reason: str
) -> PlatformSettingEntry:
    """A new value from an operator of the key's level; `value=None` gives it
    back to the deployment's or the code's. The whole change is one entry."""
    spec = platform_spec(key)
    if operator_level(operator) < spec.operator_level:
        raise ValidationError(
            {"key": [f"Ten klucz zmienia operator poziomu {spec.operator_level}."]},
            code="operator_level_required",
        )
    reason = reason.strip()
    if not reason:
        raise ValidationError({"reason": ["Podaj powód: trafia do historii."]}, code="required")
    stored = None
    if value is not None:
        checked = check_value(spec, value)
        if checked is None or checked[1]:
            message, code = (checked[1], checked[2]) if checked else ("Zła wartość.", "invalid")
            raise ValidationError({"value": [message]}, code=code)
        stored = checked[0]
    entry = PlatformSettingEntry.objects.create(
        key=key, value=stored, operator=operator, reason=reason
    )
    # Every process reads the next version's map once the change commits.
    transaction.on_commit(_bump)
    return entry


def platform_history(key: str, *, limit: int = 50) -> list[PlatformSettingEntry]:
    platform_spec(key)
    return list(
        PlatformSettingEntry.objects.filter(key=key)
        .select_related("operator")
        .order_by("-created_at", "-id")[:limit]
    )


def _bump() -> None:
    try:
        cache.incr(_VERSION_KEY)
    except ValueError:
        cache.set(_VERSION_KEY, 2, None)
