"""The company's settings on one registry (ADR-078): declarations checked at
start, values resolved with their source, one write contract — and the first
two groups, booking reminders (B5) and the online-booking pause (B1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.models import (
    Membership,
    OrganizationAuditEntry,
    OrganizationSetting,
    Role,
    RoleScope,
)
from saas_core.modules.core.organizations.permissions import SYSTEM_ROLE_PERMISSIONS
from saas_core.modules.core.organizations.settings_registry import (
    SettingArea,
    SettingGroup,
    SettingSpec,
    area_problems,
    register_setting_area,
    register_setting_group,
    registered_areas,
    schema_entry,
    settings_defaults_problems,
)
from saas_core.modules.core.organizations.settings_service import (
    SettingsEntitlementRequired,
    SettingsIdempotencyConflict,
    SettingsVersionConflict,
    change_settings,
    read_group,
    resolve,
    schema,
    validate_settings,
)
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.booking.company_settings import reminder_due
from saas_core.modules.shared.booking.models import Appointment, PublicBookingRoute, ReminderRoute
from test_booking import _no_delivery, catalog, create, membership, tenant

pytestmark = pytest.mark.django_db(transaction=True)

PASSWORD = "Bezpieczne-Haslo-2026!"
REMINDERS = "booking.reminders"
ONLINE = "booking.online"


def _change(group: str, version: str, key: str = "", **changes: Any) -> Any:
    reset = changes.pop("reset", ())
    preview = changes.pop("preview", False)
    return change_settings(
        group,
        changes=changes,
        reset=reset,
        expected_version=version,
        idempotency_key=key,
        preview=preview,
    )


def test_a_declaration_that_breaks_the_contract_stops_the_start() -> None:
    def group(**spec: Any) -> SettingGroup:
        return SettingGroup(
            key="booking.broken",
            module="shared.booking",
            title={"pl": "Zepsute", "en": "Broken"},
            description={"pl": "Opis", "en": "Description"},
            permission="organization.settings.manage",
            settings=(
                SettingSpec(**{
                    "key": "booking.broken.hours",
                    "type": "int",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                    "label": {"pl": "Godziny", "en": "Hours"},
                    "model_description": "Hours.",
                    **spec,
                }),
            ),
        )

    for broken, problem in (
        ({"default": 11}, "wartość domyślna"),
        ({"label": {"pl": "Godziny"}}, "etykieta"),
        ({"key": "booking.other.hours"}, "klucz ma postać"),
        ({"type": "float"}, "nieznany typ"),
        ({"model_description": " "}, "model_description"),
        ({"platform_env": "NO_SUCH_SETTING"}, "brak ustawienia"),
    ):
        with pytest.raises(ImproperlyConfigured, match=problem):
            register_setting_group(group(**broken))


def test_without_a_choice_the_platform_and_the_code_decide() -> None:
    member = membership("settings-defaults")
    with tenant(member):
        lead, enabled, paused = (
            resolve(f"{REMINDERS}.lead_hours"),
            resolve(f"{REMINDERS}.enabled"),
            resolve(f"{ONLINE}.paused"),
        )
    # 24 h comes from .env (BOOKING_REMINDER_LEAD_HOURS): the platform's value.
    assert (lead.value, lead.source) == (24, "platform")
    assert (enabled.value, enabled.source) == (True, "code")
    assert (paused.value, paused.source) == (False, "code")


def test_a_change_has_a_version_a_receipt_a_history_and_a_reset() -> None:
    member = membership("settings-change")
    other = membership("settings-other")
    with tenant(member):
        version = read_group(REMINDERS).version
        preview = _change(REMINDERS, version, preview=True, lead_hours=48)
        assert preview.changes == {"lead_hours": {"from": 24, "to": 48}}
        assert not OrganizationSetting.objects.exists()

        changed = _change(REMINDERS, version, "k-1", lead_hours=48)
        again = _change(REMINDERS, version, "k-1", lead_hours=48)
        state = read_group(REMINDERS)
        assert (state.values["lead_hours"].value, state.values["lead_hours"].source) == (
            48,
            "organization",
        )
        assert again.replayed is not None and again.version == changed.version == state.version
        with pytest.raises(SettingsIdempotencyConflict):
            _change(REMINDERS, version, "k-1", lead_hours=72)
        with pytest.raises(SettingsVersionConflict):
            _change(REMINDERS, version, "k-2", lead_hours=72)

        # null keeps the value; only `reset` gives it back to the platform's.
        kept = _change(REMINDERS, state.version, "k-3", lead_hours=None)
        assert kept.version == state.version
        reset = _change(REMINDERS, state.version, "k-4", reset=["lead_hours"])
        assert reset.after["lead_hours"] == 24
        assert resolve(f"{REMINDERS}.lead_hours").source == "platform"
        # The row stays with its version, so a form read before cannot match again.
        assert read_group(REMINDERS).version not in (version, state.version)

        with pytest.raises(ValidationError) as refused:
            _change(REMINDERS, reset.version, "k-5", lead_hours=0, min_notice_hours="2")
        assert {
            field: [e.code for e in errors] for field, errors in refused.value.detail.items()
        } == {
            "lead_hours": ["min_value"],
            "min_notice_hours": ["invalid"],
        }
    with tenant(other):
        assert resolve(f"{REMINDERS}.lead_hours").source == "platform"

    rows = OrganizationAuditEntry.objects.filter(
        organization=member.organization, action="organization.settings_changed"
    ).order_by("occurred_at")
    assert [(row.target_type, row.metadata["changes"]) for row in rows] == [
        (REMINDERS, {"lead_hours": {"from": 24, "to": 48}}),
        (REMINDERS, {"lead_hours": {"from": 48, "to": 24}}),
    ]
    assert rows[1].metadata["reset"] == ["lead_hours"]


def test_only_who_manages_the_company_changes_its_settings() -> None:
    member = membership("settings-permission")
    role, _ = Role.objects.get_or_create(
        key="manager",
        organization=None,
        organization_type="",
        defaults={
            "name": "Manager",
            "scope": RoleScope.SYSTEM,
            "permissions": list(SYSTEM_ROLE_PERMISSIONS["manager"]),
            "is_immutable": True,
        },
    )
    manager = Membership.objects.create(
        organization=member.organization,
        user=User.objects.create_user(email="settings-permission-manager@example.test"),
        role=role,
    )
    with tenant(manager):
        state = read_group(REMINDERS)
        assert state.can_change is False
        with pytest.raises(OrganizationPermissionDenied):
            _change(REMINDERS, state.version, "k-1", lead_hours=48)


def test_the_plan_locks_a_group_without_its_feature() -> None:
    member = membership("settings-plan")
    EntitlementSnapshot.all_objects.filter(organization=member.organization).update(
        features={"booking.enabled": False}
    )
    with tenant(member):
        state = read_group(REMINDERS)
        assert (state.can_change, state.locked) == (False, "feature_disabled")
        with pytest.raises(SettingsEntitlementRequired):
            _change(REMINDERS, state.version, "k-1", lead_hours=48)


def test_reminders_follow_the_company_and_are_re_planned_when_it_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("settings-reminders")
    appointment = create(member, catalog(member)).appointment
    starts = appointment.starts_at
    assert appointment.reminder_due_at == starts - timedelta(hours=24)

    with tenant(member):
        version = read_group(REMINDERS).version
        preview = _change(REMINDERS, version, preview=True, lead_hours=48)
        assert [effect.summary["pl"] for effect in preview.effects] == [
            "Przeliczy przypomnienia 1 wizyt, które jeszcze nie wyszły."
        ]
        moved = _change(REMINDERS, version, "k-1", lead_hours=48)
    appointment.refresh_from_db()
    assert appointment.reminder_due_at == starts - timedelta(hours=48)
    assert ReminderRoute.objects.get(appointment_id=appointment.id).due_at == starts - timedelta(
        hours=48
    )

    with tenant(member):
        _change(REMINDERS, moved.version, "k-2", enabled=False)
    appointment.refresh_from_db()
    assert appointment.reminder_due_at is None
    assert not ReminderRoute.objects.filter(appointment_id=appointment.id).exists()


def test_a_visit_too_close_to_its_start_gets_no_reminder_when_the_company_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
    monkeypatch.setattr(timezone, "now", lambda: now)
    member = membership("settings-min-notice")
    soon, later = now + timedelta(hours=2), now + timedelta(days=2)
    with tenant(member):
        # Today's behaviour: a booking for this afternoon is reminded at once.
        assert (reminder_due(soon), reminder_due(later)) == (now, later - timedelta(hours=24))
        _change(REMINDERS, read_group(REMINDERS).version, "k-1", min_notice_hours=6)
        assert (reminder_due(soon), reminder_due(later)) == (None, later - timedelta(hours=24))


def test_a_paused_company_refuses_online_bookings_and_the_team_books_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    # The public form is throttled per client address; start with a fresh allowance.
    cache.clear()
    member = membership("settings-paused")
    configured = catalog(member)
    PublicBookingRoute.objects.create(
        public_slug="wstrzymane", organization_id=member.organization_id
    )
    client = APIClient()
    url = "/api/v1/booking/public/wstrzymane"
    with tenant(member):
        _change(ONLINE, read_group(ONLINE).version, "k-1", paused=True)
    day = configured["date"]
    query = {
        "service_id": str(configured["service"].id),
        "location_id": str(configured["location"].id),
    }
    listing = client.get(f"{url}/")
    times = client.get(f"{url}/slots/", {**query, "from": str(day), "to": str(day)})
    refused = client.post(
        f"{url}/appointments/",
        {
            **query,
            "starts_at": times.json()["items"][0]["starts_at"],
            "customer": {"display_name": "Anna", "email": "anna@example.test"},
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="wstrzymane-1",
    )

    assert {key: listing.json()["online"][key] for key in ("paused", "resume_on")} == {
        "paused": True,
        "resume_on": None,
    }
    assert (refused.status_code, refused.json()["code"]) == (409, "booking_paused")
    assert create(member, configured).appointment.id
    assert Appointment.all_objects.count() == 1

    # A pause until a day that has come is over by itself.
    with tenant(member):
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        _change(ONLINE, read_group(ONLINE).version, "k-2", resume_on=yesterday)
    online = client.get(f"{url}/").json()["online"]
    assert (online["paused"], online["resume_on"]) == (False, None)


def test_the_api_reads_previews_and_changes_a_group_with_a_key() -> None:
    member = membership("settings-api")
    user = User.objects.get(pk=member.user_id)
    user.set_password(PASSWORD)
    user.save()
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf/").data["csrf_token"]
    assert (
        client.post(
            "/api/v1/auth/login/",
            {"email": user.email, "password": PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        ).status_code
        == 200
    )
    base = "/api/v1/organizations/current/settings"
    token = client.cookies["csrftoken"].value

    schema = client.get(f"{base}/schema/")
    group = client.get(f"{base}/{REMINDERS}/")
    without_key = client.patch(
        f"{base}/{REMINDERS}/",
        {"expected_version": group.json()["version"], "lead_hours": 48},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    wrong = client.post(
        f"{base}/{REMINDERS}/preview/",
        {"expected_version": group.json()["version"], "lead_hours": 500},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    changed = client.patch(
        f"{base}/{REMINDERS}/",
        {"expected_version": group.json()["version"], "lead_hours": 48},
        format="json",
        HTTP_X_CSRFTOKEN=token,
        HTTP_IDEMPOTENCY_KEY="api-1",
    )

    groups = {entry["key"]: entry for entry in schema.json()["groups"]}
    assert {REMINDERS, ONLINE} <= set(groups)
    # The places of „Ustawienia” in menu order (33a): every group stands in one,
    # an area without a page of its own is drawn by the generic one.
    areas = {area["key"]: area for area in schema.json()["areas"]}
    assert list(areas)[:2] == ["company", "security"]
    assert {group["area"] for group in groups.values()} == set(areas)
    assert areas["company"]["page"] == "/panel/settings/company"
    assert areas["security"]["page"] is None
    # A product may give the area its own words (relabel_settings, UX-082).
    assert areas["customer-emails"]["title"] == dict(
        next(area for area in registered_areas() if area.key == "customer-emails").title
    )
    assert groups[REMINDERS]["can_change"] is True
    assert [key["key"] for key in groups[REMINDERS]["keys"]] == [
        "booking.reminders.enabled",
        "booking.reminders.lead_hours",
        "booking.reminders.min_notice_hours",
    ]
    assert group.json()["values"]["lead_hours"] == 24
    assert group.json()["sources"]["lead_hours"] == "platform"
    assert without_key.status_code == 400
    assert without_key.json()["errors"][0]["field"] == "idempotency_key"
    assert wrong.status_code == 400
    assert wrong.json()["errors"][0]["field"] == "lead_hours"
    assert changed.status_code == 200
    assert changed.json()["values"]["lead_hours"] == 48
    assert changed.json()["sources"]["lead_hours"] == "organization"


def _entity_group(**spec: Any) -> SettingGroup:
    return SettingGroup(
        key="booking.entity_probe",
        module="shared.booking",
        title={"pl": "Próba", "en": "Probe"},
        description={"pl": "Opis", "en": "Description"},
        permission="organization.settings.manage",
        api="/api/v1/booking/probe/",
        read_explicit=lambda: {"mode": None},
        settings=(
            SettingSpec(**{
                "key": "booking.entity_probe.mode",
                "type": "enum",
                "values": (
                    ("a", {"pl": "A", "en": "A"}),
                    ("b", {"pl": "B", "en": "B"}),
                ),
                "default": "a",
                "scopes": ("organization",),
                "label": {"pl": "Tryb", "en": "Mode"},
                "model_description": "Mode.",
                **spec,
            }),
        ),
    )


def test_an_entity_group_is_declared_by_core_and_written_by_its_module(
    settings: Any,
) -> None:
    """ADR-078 pkt 7 (R2b): an entity group's module keeps its table and API;
    the registry checks its keys and lists them with `api`."""
    with pytest.raises(ImproperlyConfigured, match="restrict"):
        register_setting_group(_entity_group(strategy="restrict", type="bool", values=()))
    with pytest.raises(ImproperlyConfigured, match="read_explicit czyta tylko"):
        register_setting_group(_entity_group(scopes=("offer",)))
    settings.SETTINGS_DEFAULTS = {"booking.entity_probe.mode": "b"}
    with pytest.raises(ImproperlyConfigured, match="settingsDefaults"):
        register_setting_group(_entity_group(product_default=False))

    member = membership("settings-basics")
    with tenant(member):
        currency, mode = resolve("organization.currency"), resolve("booking.reminders.lead_hours")
        assert (currency.value, currency.source) == ("PLN", "organization")
        assert mode.source == "platform"
        with pytest.raises(NotFound):
            _change("organization", "x", currency="EUR")
        with pytest.raises(ValidationError) as refused:
            validate_settings("organization", {"currency": "GBP"})
    assert refused.value.detail["currency"][0].code == "invalid_choice"


def test_the_schema_names_who_serves_a_group_and_how_its_value_applies() -> None:
    member = membership("settings-schema")
    with tenant(member) as context:
        groups = {group.key: (group, can, locked) for group, can, locked in schema(context)}
    basics = groups["organization"][0]
    assert basics.api == "/api/v1/organizations/current/"
    assert groups[REMINDERS][0].api is None
    entry = schema_entry(basics.spec("currency"))
    assert (entry["strategy"], entry["scopes"]) == ("override", ["organization"])


def test_an_area_is_an_address_with_texts_and_every_group_stands_in_one() -> None:
    with pytest.raises(ImproperlyConfigured, match="małe litery"):
        register_setting_area(SettingArea(key="Zła Nazwa", title=_TEXT, description=_TEXT, order=1))
    with pytest.raises(ImproperlyConfigured, match="pl i en"):
        register_setting_area(
            SettingArea(key="probe-area", title={"pl": "Tylko pl"}, description=_TEXT, order=1)
        )
    assert area_problems() == []


_TEXT = {"pl": "Tekst", "en": "Text"}


def test_a_product_default_nobody_declares_fails_the_start(settings: Any) -> None:
    settings.SETTINGS_DEFAULTS = {
        "booking.reminders.lead_hours": 48,
        "booking.nonexistent.key": 1,
        # A namespace without a registered group checks its own keys.
        "elsewhere.thing": True,
    }
    assert settings_defaults_problems() == ["booking.nonexistent.key"]
