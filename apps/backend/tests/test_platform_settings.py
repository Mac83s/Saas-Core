"""The platform's own values and who sets them (platform settings plan, phase
1: S-T1, S-T2, S-T7; ADR-078 pkt 16): an operator's value above the
deployment's and the code's, kept with who and why; level 2 an explicit grant
given on the server; a platform-only group none of a company's business."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from typing import Any

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.identity.models import (
    OperatorGrant,
    User,
    UserMfaMethod,
    UserSession,
    UserStatus,
)
from saas_core.modules.core.identity.operators import operator_level
from saas_core.modules.core.organizations import settings_registry
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE
from saas_core.modules.core.organizations.platform_settings import (
    change_platform_setting,
    platform_history,
    platform_setting,
    read_platform_setting,
)
from saas_core.modules.core.organizations.settings_registry import (
    SettingGroup,
    SettingSpec,
    register_setting_group,
)
from saas_core.modules.core.organizations.settings_service import resolve, schema
from test_booking import membership, tenant

pytestmark = pytest.mark.django_db(transaction=True)

LIMIT = "organization.platform_probe.limit"
NOTE = "organization.platform_probe.note"


@pytest.fixture(autouse=True)
def probe(monkeypatch: pytest.MonkeyPatch, settings: Any) -> Any:
    """A platform-only group of its own, on a copy of the registry; the
    deployment's `.env` gives the limit 20."""
    settings.PLATFORM_PROBE_LIMIT = 20
    monkeypatch.setattr(settings_registry, "_groups", dict(settings_registry._groups))
    monkeypatch.setattr(settings_registry, "_keys", dict(settings_registry._keys))
    cache.clear()
    register_setting_group(
        SettingGroup(
            key="organization.platform_probe",
            module="core.organizations",
            title={"pl": "Próba platformy", "en": "Platform probe"},
            description={"pl": "Opis", "en": "Description"},
            permission=SETTINGS_MANAGE,
            area="company",
            settings=(
                SettingSpec(
                    key=LIMIT,
                    type="int",
                    minimum=1,
                    maximum=100,
                    default=10,
                    scopes=("platform",),
                    platform_env="PLATFORM_PROBE_LIMIT",
                    label={"pl": "Limit", "en": "Limit"},
                    model_description="A probe limit.",
                ),
                SettingSpec(
                    key=NOTE,
                    type="text",
                    default="",
                    max_length=40,
                    scopes=("platform",),
                    operator_level=1,
                    label={"pl": "Notka", "en": "Note"},
                    model_description="A probe note.",
                ),
            ),
        )
    )
    yield
    cache.clear()


def _person(email: str, *, staff: bool = True, mfa: bool = True) -> User:
    user = User.objects.create_user(email=email, is_staff=staff)
    user.status = UserStatus.ACTIVE
    user.save()
    if mfa:
        UserMfaMethod.objects.create(user=user, secret_ciphertext="x", confirmed_at=timezone.now())
    return user


def test_an_operator_is_staff_with_2fa_and_level_2_is_a_grant_on_the_server() -> None:
    anna = _person("anna@example.test")
    assert operator_level(_person("nobody@example.test", staff=False)) == 0
    assert operator_level(_person("no-mfa@example.test", mfa=False)) == 0
    assert operator_level(anna) == 1
    UserSession.objects.create(
        user=anna, session_key_hash="a" * 64, expires_at=timezone.now() + timedelta(days=1)
    )

    # The first grant on a deployment: whoever has the server, as an operator.
    call_command(
        "operator_level",
        grant="anna@example.test",
        operator="anna@example.test",
        reason="Pierwsza administratorka",
        stdout=StringIO(),
    )
    assert operator_level(anna) == 2
    # A grant ends her sessions: the new level holds from the next sign-in.
    assert not UserSession.objects.filter(user=anna, revoked_at__isnull=True).exists()

    # From now on only level 2 gives level 2, and only with a reason.
    bob = _person("bob@example.test")
    with pytest.raises(CommandError, match="poziomu 2"):
        call_command(
            "operator_level",
            grant="bob@example.test",
            operator="bob@example.test",
            reason="Sam sobie",
            stdout=StringIO(),
        )
    with pytest.raises(CommandError, match="--reason"):
        call_command(
            "operator_level",
            grant="bob@example.test",
            operator="anna@example.test",
            stdout=StringIO(),
        )
    call_command(
        "operator_level",
        grant="bob@example.test",
        operator="anna@example.test",
        reason="Zastępstwo",
        stdout=StringIO(),
    )
    call_command(
        "operator_level",
        revoke="bob@example.test",
        operator="anna@example.test",
        reason="Koniec zastępstwa",
        stdout=StringIO(),
    )
    assert operator_level(bob) == 1
    assert OperatorGrant.objects.filter(user=bob).count() == 1


def test_the_platform_s_value_stands_above_the_deployment_s_and_keeps_its_history() -> None:
    admin = _person("admin@example.test")
    OperatorGrant.objects.create(user=admin, reason="test")
    assert (platform_setting(LIMIT), read_platform_setting(LIMIT).source) == (20, "deployment")
    assert read_platform_setting(NOTE).source == "code"

    change_platform_setting(LIMIT, 30, operator=admin, reason="Więcej dla pilota")
    assert (platform_setting(LIMIT), read_platform_setting(LIMIT).source) == (30, "platform")
    # No company has a say, so no tenant is needed to read it.
    assert resolve(LIMIT).value == 30
    change_platform_setting(LIMIT, None, operator=admin, reason="Z powrotem")
    assert (platform_setting(LIMIT), read_platform_setting(LIMIT).source) == (20, "deployment")
    assert [(e.value, e.reason) for e in platform_history(LIMIT)] == [
        (None, "Z powrotem"),
        (30, "Więcej dla pilota"),
    ]


def test_a_key_changes_only_at_its_level_with_a_valid_value_and_a_reason() -> None:
    operator = _person("op@example.test")
    with pytest.raises(ValidationError) as low:
        change_platform_setting(LIMIT, 30, operator=operator, reason="Bez poziomu")
    assert "operator_level_required" in str(low.value.detail)
    change_platform_setting(NOTE, "Uwaga", operator=operator, reason="Poziom 1 wystarczy")
    assert platform_setting(NOTE) == "Uwaga"
    OperatorGrant.objects.create(user=operator, reason="test")
    with pytest.raises(ValidationError):
        change_platform_setting(LIMIT, 500, operator=operator, reason="Za dużo")
    with pytest.raises(ValidationError):
        change_platform_setting(LIMIT, 50, operator=operator, reason="   ")


def test_a_platform_group_is_none_of_a_company_s_business() -> None:
    member = membership("platform-probe")
    with tenant(member) as context:
        groups = {group.key for group, _can, _locked in schema(context)}
    assert "organization.platform_probe" not in groups
    assert "booking.reminders" in groups


def test_the_command_reads_changes_and_gives_back_a_value() -> None:
    admin = _person("cli@example.test")
    OperatorGrant.objects.create(user=admin, reason="test")
    out = StringIO()
    call_command(
        "platform_setting",
        "set",
        LIMIT,
        "42",
        operator="cli@example.test",
        reason="Z konsoli",
        stdout=out,
    )
    assert f"{LIMIT}\t42\tplatform\tpoziom 2" in out.getvalue()
    with pytest.raises(CommandError, match="unknown_setting|Nie ma ustawienia"):
        call_command("platform_setting", "get", "organization.nope.x", stdout=StringIO())
    call_command(
        "platform_setting",
        "reset",
        LIMIT,
        operator="cli@example.test",
        reason="Domyślnie",
        stdout=StringIO(),
    )
    assert platform_setting(LIMIT) == 20
