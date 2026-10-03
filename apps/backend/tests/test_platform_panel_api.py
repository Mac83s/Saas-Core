"""The „Platforma" panel's API (platform settings plan, phase 2; S-T5, S-T7):
operators only, on a session signed in through MFA; a level-2 key needs a
level-2 operator and a fresh code; a preview counts the companies a change
reaches; the history says who and why."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.mfa import current_totp_code
from saas_core.modules.core.identity.models import OperatorGrant, User
from saas_core.modules.core.organizations import settings_registry
from saas_core.modules.core.organizations.models import Organization, OrganizationSetting
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE
from saas_core.modules.core.organizations.platform_settings import platform_setting
from saas_core.modules.core.organizations.settings_registry import (
    SettingGroup,
    SettingSpec,
    register_setting_group,
)
from test_booking import membership, tenant
from test_identity_admin import active_user, csrf, login, operator_after_enrolment

pytestmark = pytest.mark.django_db

URL = "/api/v1/platform/settings/"
NOTE = "organization.panel_probe.note"  # platform-only, level 1
LEAD = "booking.reminders.lead_hours"  # a company key, level 2


@pytest.fixture(autouse=True)
def probe(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(settings_registry, "_groups", dict(settings_registry._groups))
    monkeypatch.setattr(settings_registry, "_keys", dict(settings_registry._keys))
    cache.clear()
    register_setting_group(
        SettingGroup(
            key="organization.panel_probe",
            module="core.organizations",
            title={"pl": "Próba panelu", "en": "Panel probe"},
            description={"pl": "Opis", "en": "Description"},
            permission=SETTINGS_MANAGE,
            area="company",
            settings=(
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


def _post(client: APIClient, path: str, body: dict[str, Any]) -> Any:
    return client.post(path, body, format="json", HTTP_X_CSRFTOKEN=csrf(client))


def _keys(listing: Any) -> dict[str, dict[str, Any]]:
    return {key["key"]: key for group in listing.data["groups"] for key in group["keys"]}


def test_only_an_operator_signed_in_through_mfa_gets_in() -> None:
    member = APIClient(enforce_csrf_checks=True)
    assert login(member, active_user("member@example.test", staff=False)).status_code == 200
    assert member.get(URL).status_code == 403
    assert member.get("/api/v1/auth/me/").data["operator_level"] == 0

    operator, _secret = operator_after_enrolment()
    listing = operator.get(URL)
    assert listing.status_code == 200, listing.data
    assert listing.data["operator_level"] == 1
    assert operator.get("/api/v1/auth/me/").data["operator_level"] == 1
    keys = _keys(listing)
    assert {name: keys[NOTE][name] for name in ("value", "source", "can_change")} == {
        "value": "",
        "source": "code",
        "can_change": True,
    }
    assert (keys[LEAD]["operator_level"], keys[LEAD]["can_change"]) == (2, False)
    assert all("platform" in key["scopes"] for key in keys.values())
    assert "company" in {area["key"] for area in listing.data["areas"]}


def test_a_level_1_operator_changes_a_level_1_key_with_a_reason(
    django_capture_on_commit_callbacks: Any,
) -> None:
    operator, _secret = operator_after_enrolment()
    # The list fills the cached map: the answer to the change must not read
    # it, because the map moves only when the request's transaction commits.
    assert _keys(operator.get(URL))[NOTE]["value"] == ""
    assert _post(operator, f"{URL}{NOTE}/", {"value": "Hej", "reason": ""}).status_code == 400
    with django_capture_on_commit_callbacks(execute=True):
        changed = _post(operator, f"{URL}{NOTE}/", {"value": "Hej", "reason": "Na próbę"})
        again = _post(operator, f"{URL}{NOTE}/", {"value": "Hej", "reason": "Na próbę"})
    history = operator.get(f"{URL}{NOTE}/history/")

    assert (changed.status_code, again.status_code) == (200, 200), changed.data
    assert (changed.data["value"], changed.data["source"]) == ("Hej", "platform")
    assert _keys(operator.get(URL))[NOTE]["source"] == "platform"
    assert [
        (item["value"], item["operator"], item["reason"]) for item in history.data["items"]
    ] == [("Hej", "operator@example.test", "Na próbę")]
    refused = _post(operator, f"{URL}{LEAD}/", {"value": 48, "reason": "Pilot"})
    assert [error["code"] for error in refused.data["errors"]] == ["operator_level_required"]


def test_a_level_2_key_takes_a_level_2_operator_and_a_fresh_code(
    django_capture_on_commit_callbacks: Any,
) -> None:
    operator, secret = operator_after_enrolment()
    OperatorGrant.objects.create(user=User.objects.get(email="operator@example.test"), reason="t")
    without_code = _post(operator, f"{URL}{LEAD}/", {"value": 48, "reason": "Pilot"})
    assert without_code.status_code == 403
    assert without_code.data["code"] == "step_up_required"

    stepped = _post(
        operator,
        "/api/v1/auth/step-up/",
        {"code": current_totp_code(secret, at=timezone.now().timestamp() + 30)},
    )
    assert stepped.status_code == 200, stepped.data
    with django_capture_on_commit_callbacks(execute=True):
        changed = _post(operator, f"{URL}{LEAD}/", {"value": 48, "reason": "Pilot"})
    assert (changed.status_code, changed.data["value"], changed.data["source"]) == (
        200,
        48,
        "platform",
    )


def test_a_preview_counts_the_companies_with_no_value_of_their_own() -> None:
    operator, _secret = operator_after_enrolment()
    membership("following")
    own = membership("own")
    with tenant(own):
        OrganizationSetting.objects.create(organization=own.organization, key=LEAD, value=12)

    preview = _post(operator, f"{URL}{LEAD}/preview/", {"value": 48, "reason": "Pilot"})
    platform_only = _post(operator, f"{URL}{NOTE}/preview/", {"value": "x", "reason": "Próba"})
    wrong = _post(operator, f"{URL}{LEAD}/preview/", {"value": 5000, "reason": "Za dużo"})
    unknown = operator.get(f"{URL}organization.nope.x/history/")

    assert preview.status_code == 200, preview.data
    assert (preview.data["current"], preview.data["proposed"]) == (platform_setting(LEAD), 48)
    assert preview.data["companies_following"] == Organization.objects.count() - 1
    assert platform_only.data["companies_following"] is None
    assert (wrong.status_code, unknown.status_code) == (400, 400)


def test_an_operator_without_a_company_has_an_empty_inbox_not_an_error() -> None:
    """The panel's bell asks on every page; an account outside any company
    has no company's inbox (found by the browser walk-through of „Platforma")."""
    operator, _secret = operator_after_enrolment()

    inbox = operator.get("/api/v1/notifications/inbox/")
    read = _post(operator, "/api/v1/notifications/inbox/read/", {})

    assert (inbox.status_code, inbox.data["items"], inbox.data["unread"]) == (200, [], 0)
    assert read.status_code == 200


WAIT = "organization.wait_probe.wait_minutes"
MAX_WAIT = "organization.wait_probe.max_wait_minutes"
OWN = "organization.own_probe.mode"


def _wait(field: str, default: int) -> SettingSpec:
    return SettingSpec(
        key=f"organization.wait_probe.{field}",
        type="int",
        minimum=1,
        maximum=240,
        default=default,
        scopes=("platform",),
        operator_level=1,
        label={"pl": field, "en": field},
        model_description="A probe wait.",
    )


def test_a_rule_between_two_platform_keys_is_kept_by_the_change_and_the_preview(
    django_capture_on_commit_callbacks: Any,
) -> None:
    def longest_not_below(_before: Any, after: Any) -> dict[str, tuple[str, str]]:
        if after["max_wait_minutes"] < after["wait_minutes"]:
            return {
                "max_wait_minutes": ("Najdłuższe czekanie nie krótsze niż zwykłe.", "below_wait")
            }
        return {}

    register_setting_group(
        SettingGroup(
            key="organization.wait_probe",
            module="core.organizations",
            title={"pl": "Czekanie", "en": "Waiting"},
            description={"pl": "Opis", "en": "Description"},
            permission=SETTINGS_MANAGE,
            area="company",
            platform_check=longest_not_below,
            settings=(_wait("wait_minutes", 5), _wait("max_wait_minutes", 30)),
        )
    )
    operator, _secret = operator_after_enrolment()

    # Raising the wait above the longest breaks the rule whichever key moves.
    preview = _post(operator, f"{URL}{WAIT}/preview/", {"value": 40, "reason": "Próba"})
    refused = _post(operator, f"{URL}{WAIT}/", {"value": 40, "reason": "Próba"})
    assert (preview.status_code, refused.status_code) == (400, 400)
    assert [(e["field"], e["code"]) for e in refused.data["errors"]] == [("value", "below_wait")]

    with django_capture_on_commit_callbacks(execute=True):
        assert (
            _post(operator, f"{URL}{MAX_WAIT}/", {"value": 60, "reason": "Dłużej"}).status_code
            == 200
        )
    with django_capture_on_commit_callbacks(execute=True):
        assert _post(operator, f"{URL}{WAIT}/", {"value": 40, "reason": "Próba"}).status_code == 200
    # Giving the longest wait back to its default (30) would fall below 40.
    back = _post(operator, f"{URL}{MAX_WAIT}/", {"value": None, "reason": "Wraca"})
    assert (back.status_code, back.data["errors"][0]["code"]) == (400, "below_wait")


def test_a_products_own_default_stands_above_the_platforms_and_the_panel_says_so(
    settings: Any,
) -> None:
    membership("pod-produktem")
    operator, _secret = operator_after_enrolment()
    before = _post(operator, f"{URL}{LEAD}/preview/", {"value": 48, "reason": "Pilot"})
    assert before.data["product_value"] is None and before.data["companies_following"] >= 1

    settings.SETTINGS_DEFAULTS = {LEAD: 36}

    preview = _post(operator, f"{URL}{LEAD}/preview/", {"value": 48, "reason": "Pilot"})
    listed = _keys(operator.get(URL))[LEAD]
    # The company gets the product's 36, whatever the operator sets.
    assert (preview.data["companies_following"], preview.data["product_value"]) == (0, 36)
    assert listed["product_value"] == 36
    assert _keys(operator.get(URL))[NOTE]["product_value"] is None


def test_companies_with_a_value_in_a_modules_own_table_are_counted_through_it() -> None:
    from saas_core.modules.core.organizations.context import (  # noqa: PLC0415
        require_tenant_context,
    )

    first, second = membership("wlasna-tabela"), membership("bez-wlasnej")

    def explicit() -> dict[str, Any]:
        # The module's own table: only the first company chose a mode.
        mine = require_tenant_context().organization_id == first.organization_id
        return {"mode": "review" if mine else None}

    register_setting_group(
        SettingGroup(
            key="organization.own_probe",
            module="core.organizations",
            title={"pl": "Własna tabela", "en": "Own table"},
            description={"pl": "Opis", "en": "Description"},
            permission=SETTINGS_MANAGE,
            area="company",
            api="/api/v1/organizations/own-probe/",
            read_explicit=explicit,
            settings=(
                SettingSpec(
                    key=OWN,
                    type="enum",
                    default="automatic",
                    values=(
                        ("automatic", {"pl": "Automat", "en": "Automatic"}),
                        ("review", {"pl": "Przegląd", "en": "Review"}),
                    ),
                    label={"pl": "Tryb", "en": "Mode"},
                    model_description="A probe mode.",
                ),
            ),
        )
    )
    operator, _secret = operator_after_enrolment()
    OperatorGrant.objects.create(user=User.objects.get(email="operator@example.test"), reason="t")

    preview = _post(operator, f"{URL}{OWN}/preview/", {"value": "review", "reason": "Próba"})

    assert preview.status_code == 200, preview.data
    assert second.organization_id != first.organization_id
    assert preview.data["companies_following"] == Organization.objects.count() - 1
