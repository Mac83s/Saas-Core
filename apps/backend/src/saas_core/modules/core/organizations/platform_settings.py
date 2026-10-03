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

from .context import TenantContext, activate_tenant_context, set_local_organization_id
from .models import Organization, OrganizationSetting, PlatformSettingEntry
from .pre_tenant import PRE_TENANT_DB
from .settings_registry import (
    SettingSpec,
    check_value,
    live_product_value,
    setting_group,
    setting_spec,
)

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
    spec = platform_spec(key)
    chosen = platform_overrides().get(key)
    if chosen is not None:
        return PlatformValue(key, chosen, "platform", spec.operator_level)
    return _below_the_operator(spec)


def value_after(entry: PlatformSettingEntry) -> PlatformValue:
    """The value in force once `entry` commits — for the answer to the change
    itself: a request runs in a transaction, so the cached map still holds the
    value from before until the request ends."""
    spec = platform_spec(entry.key)
    if entry.value is not None:
        return PlatformValue(entry.key, entry.value, "platform", spec.operator_level)
    return _below_the_operator(spec)


def _below_the_operator(spec: SettingSpec) -> PlatformValue:
    from django.conf import settings  # noqa: PLC0415

    if spec.platform_env is not None and getattr(settings, spec.platform_env, None) is not None:
        return PlatformValue(
            spec.key, getattr(settings, spec.platform_env), "deployment", spec.operator_level
        )
    return PlatformValue(spec.key, spec.default, "code", spec.operator_level)


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
    stored = checked_platform_value(key, value)
    latest = PlatformSettingEntry.objects.filter(key=key).order_by("-created_at", "-id").first()
    if latest is not None and (latest.value, latest.reason, latest.operator_id) == (
        stored,
        reason,
        operator.pk,
    ):
        # The same change sent twice (a retried click) is one entry.
        return latest
    entry = PlatformSettingEntry.objects.create(
        key=key, value=stored, operator=operator, reason=reason
    )
    # Every process reads the next version's map once the change commits.
    transaction.on_commit(_bump)
    return entry


def checked_platform_value(key: str, value: Any) -> Any:
    """`value` as the platform would store it — None gives the key back —
    after the key's own check and its group's rule between keys
    (`platform_check`); what the change and its preview both refuse."""
    spec = platform_spec(key)
    stored = None
    if value is not None:
        checked = check_value(spec, value)
        if checked is None or checked[1]:
            message, code = (checked[1], checked[2]) if checked else ("Zła wartość.", "invalid")
            raise ValidationError({"value": [message]}, code=code)
        stored = checked[0]
    group = setting_group(spec.group)
    if group.platform_check is not None:
        before = {
            other.field: read_platform_setting(other.key).value
            for other in group.settings
            if "platform" in other.scopes
        }
        after = {
            **before,
            spec.field: stored if stored is not None else _below_the_operator(spec).value,
        }
        problems = dict(group.platform_check(before, after))
        if problems:
            # One value is being changed: whatever rule breaks is said on it.
            message, code = problems.get(spec.field) or next(iter(problems.values()))
            raise ValidationError({"value": [message]}, code=code)
    return stored


def product_shadow(key: str) -> Any:
    """The product's own starting value of a company key on this deployment
    (`settingsDefaults`, read live), or None. Where it exists, a company with
    no value of its own gets it — not the platform's: the product stands above
    the platform in the registry's order (ADR-078 pkt 3)."""
    spec = platform_spec(key)
    return live_product_value(spec) if "organization" in spec.scopes else None


def companies_following(key: str) -> int | None:
    """How many companies have no value of their own for a company key, so a
    change of the platform's reaches them at once; None for a key companies do
    not set (or whose company values this code cannot read). Zero where the
    product's own default stands above the platform's. A number only: like the
    billing sweeps (ADR-039), the door lists the companies and each one's rows
    are read inside its own tenant — a module's own table through the group's
    `read_explicit`."""
    spec = platform_spec(key)
    if "organization" not in spec.scopes:
        return None
    group = setting_group(spec.group)
    if group.api is not None and group.read_explicit is None:
        return None
    if product_shadow(key) is not None:
        return 0
    # ADR-041: the operator has no tenant; the list of companies is the read.
    identifiers = Organization.objects.using(PRE_TENANT_DB).values_list("id", flat=True)
    following = 0
    for organization_id in identifiers:
        with transaction.atomic():
            set_local_organization_id(organization_id)
            if group.read_explicit is not None:
                # The module's own table: read as the company itself would.
                reader = TenantContext(
                    organization_id=organization_id,
                    membership_id=organization_id,
                    actor_id=organization_id,
                    role_key="platform_preview",
                    permissions=frozenset(),
                    principal_kind="service",
                )
                with activate_tenant_context(reader):
                    own = group.read_explicit().get(spec.field) is not None
            else:
                own = OrganizationSetting.objects.filter(
                    organization_id=organization_id, key=key, value__isnull=False
                ).exists()
            if not own:
                following += 1
    return following


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
