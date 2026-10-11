"""A module's kind of visit brings its own booking-form fields (ADR-072 §10).

The descriptor's `appointmentKindFields` are copied onto a service when it is
made, by the road a preset's fields take, and `booking_apply_kind_fields`
completes services that exist. The core names no product: these tests use a
descriptor of their own."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from saas_core.config.composition import CompositionError, kind_fields_for, load_catalog
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.booking import services as booking_services
from saas_core.modules.shared.booking import setup as booking_setup
from saas_core.modules.shared.booking.form_fields import list_fields
from saas_core.modules.shared.booking.models import FormField, Service
from saas_core.modules.shared.booking.presets import apply_preset
from saas_core.modules.shared.booking.services import create_catalog_item
from saas_core.modules.shared.booking.setup import save_service
from test_booking import _no_delivery, membership, tenant
from test_booking_prices import key

pytestmark = pytest.mark.django_db

KIND = "example.visit"
FIELDS = (
    {
        "key": "count",
        "type": "number",
        "mandatory": True,
        "mandatoryForStaff": False,
        "labels": {"pl": "Liczba sztuk", "en": "Number of animals"},
    },
    {
        "key": "note",
        "type": "long_text",
        "mandatory": False,
        "labels": {"pl": "Notatka", "en": "Note"},
    },
)


@pytest.fixture(autouse=True)
def declared(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_delivery(monkeypatch)
    monkeypatch.setattr(settings, "APPOINTMENT_KIND_FIELDS", {KIND: FIELDS}, raising=False)
    for module in (booking_services, booking_setup):
        monkeypatch.setattr(module, "_assert_appointment_kind_available", lambda *_: None)


def made(owner: Any, name: str, kind: str = KIND) -> Service:
    with tenant(owner):
        return save_service(
            service_id=None,
            data={"name": name, "duration_minutes": 30, "appointment_kind": kind},
            idempotency_key=key(),
        ).value.service


def asked(owner: Any, service: Service) -> list[tuple[str, str, bool, bool, int]]:
    with tenant(owner):
        return [
            (f.name, f.kind, f.mandatory, f.mandatory_for_staff, f.position)
            for f in list_fields()
            if f.service_id == service.id
        ]


EXPECTED = [
    ("Liczba sztuk", "number", True, False, 1),
    ("Notatka", "long_text", False, True, 2),
]


def test_a_service_of_the_kind_gets_its_fields_when_made() -> None:
    owner = membership("kf-setup")
    assert asked(owner, made(owner, "Korekcja")) == EXPECTED


def test_a_service_of_another_kind_or_none_gets_none() -> None:
    owner = membership("kf-other")
    assert asked(owner, made(owner, "Plain", kind="")) == []
    assert asked(owner, made(owner, "Elsewhere", kind="example.other")) == []


def test_the_catalogue_road_copies_them_too() -> None:
    owner = membership("kf-catalog")
    with tenant(owner):
        item = create_catalog_item(
            kind="service", data={"name": "Korekcja", "appointment_kind": KIND}
        )
    assert asked(owner, item) == EXPECTED


def test_a_second_service_is_not_blocked_by_the_names_of_the_first() -> None:
    owner = membership("kf-two")
    made(owner, "A")
    assert asked(owner, made(owner, "B")) == EXPECTED


def test_a_preset_offer_keeps_the_presets_fields_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The preset sets no kind today; with one it would copy the preset's fields
    and then the kind's, which `copy_kind_fields` guarantees by position."""
    from saas_core.modules.shared.booking.form_fields import copy_kind_fields  # noqa: PLC0415

    owner = membership("kf-preset")
    with tenant(owner) as context:
        saved = apply_preset(preset_id="core.rental", name="Wynajem", idempotency_key=key())
        service = saved.value.service
        before = FormField.all_objects.filter(service_id=service.id).count()
        Service.all_objects.filter(pk=service.id).update(appointment_kind=KIND)
        service.refresh_from_db()
        organization = Organization.objects.get(pk=context.organization_id)
        copy_kind_fields(context, organization, service)
        names = list(
            FormField.all_objects.filter(service_id=service.id)
            .order_by("position")
            .values_list("name", flat=True)
        )
    assert names[-2:] == ["Liczba sztuk", "Notatka"]
    assert len(names) == before + 2


def _run(*args: str, **options: Any) -> str:
    out = StringIO()
    call_command("booking_apply_kind_fields", *args, stdout=out, **options)
    return out.getvalue()


def _bare_services(owner: Any, *names: str) -> list[Service]:
    """Services of the kind made before the module declared its fields."""
    with tenant(owner):
        return [
            Service.all_objects.create(
                organization=owner.organization,
                name=name,
                public_slug=name.lower(),
                duration_minutes=30,
                appointment_kind=KIND,
            )
            for name in names
        ]


def _count(service: Service) -> int:
    return FormField.all_objects.filter(service_id=service.id).count()


def test_the_command_writes_nothing_without_apply() -> None:
    owner = membership("kf-dry")
    first, second = _bare_services(owner, "Alpha", "Beta")
    output = _run(organization=str(owner.organization_id))
    assert output.rstrip().endswith("Usługi: 2, dodane pola: 4.")
    assert "dodałbym Liczba sztuk, Notatka" in output
    assert (_count(first), _count(second)) == (0, 0)


def test_apply_adds_and_a_second_run_adds_nothing() -> None:
    owner = membership("kf-apply")
    first, _plain = _bare_services(owner, "Alpha", "Beta")
    _run("--apply", organization=str(owner.organization_id))
    assert asked(owner, first) == EXPECTED
    again = _run("--apply", organization=str(owner.organization_id))
    assert again.rstrip().endswith("Usługi: 0, dodane pola: 0.")
    assert _count(first) == 2


def test_a_service_that_already_has_the_name_is_skipped_even_when_switched_off() -> None:
    owner = membership("kf-skip")
    (service,) = _bare_services(owner, "Alpha")
    FormField.all_objects.create(
        organization=owner.organization,
        service=service,
        name="liczba sztuk",
        kind="text",
        mandatory=False,
        active=False,
        position=1,
    )
    output = _run("--apply", organization=str(owner.organization_id))
    assert output.rstrip().endswith("Usługi: 1, dodane pola: 1.")
    names = list(
        FormField.all_objects.filter(service_id=service.id)
        .order_by("position")
        .values_list("name", "kind", "active")
    )
    # Its own field is untouched; only the missing one was added, after it.
    assert names == [("liczba sztuk", "text", False), ("Notatka", "long_text", True)]


def test_organization_narrows_the_run() -> None:
    mine, other = membership("kf-mine"), membership("kf-theirs")
    (mine_service,) = _bare_services(mine, "Alpha")
    (other_service,) = _bare_services(other, "Beta")
    _run("--apply", organization=str(mine.organization_id))
    assert (_count(mine_service), _count(other_service)) == (2, 0)
    _run("--apply")
    assert _count(other_service) == 2


def test_the_command_sets_the_tenant_before_its_first_tenant_read() -> None:
    """The test database bypasses row-level security, so the order is asserted
    on the statements: under the app's role a read before `SET LOCAL` is empty."""
    owner = membership("kf-order")
    _bare_services(owner, "Alpha")
    with CaptureQueriesContext(connection) as captured:
        _run("--apply", organization=str(owner.organization_id))
    sql = [query["sql"] for query in captured.captured_queries]
    tenant_index = next(i for i, text in enumerate(sql) if "app.organization_id" in text)
    for table in ("booking_service", "booking_formfield"):
        touched = next(i for i, text in enumerate(sql) if table in text)
        assert tenant_index < touched, f"{table} read before SET LOCAL"


def test_the_command_audits_as_the_system_and_refuses_a_bad_organization() -> None:
    from saas_core.modules.core.organizations.models import OrganizationAuditEntry  # noqa: PLC0415

    owner = membership("kf-audit")
    _bare_services(owner, "Alpha")
    _run("--apply", organization=str(owner.organization_id))
    from saas_core.modules.shared.booking.rules import FIELD_CHANGED  # noqa: PLC0415

    rows = OrganizationAuditEntry.objects.filter(
        organization_id=owner.organization_id, action=FIELD_CHANGED
    )
    assert rows.count() == 2
    assert all(row.actor_user_id is None for row in rows)
    with pytest.raises(CommandError):
        _run(organization="not-a-uuid")
    with pytest.raises(CommandError, match="nie istnieje"):
        _run(organization=str(UUID(int=7)))


def _descriptor(tmp_path: Path, **backend: Any) -> Path:
    descriptor = json.loads(
        (Path(settings.MODULE_CATALOG_PATH) / "core.health.json").read_text(encoding="utf-8")
    )
    descriptor["backend"]["appointmentKinds"] = {"health.visit": "Wizyta"}
    descriptor["backend"].update(backend)
    (tmp_path / "core.health.json").write_text(json.dumps(descriptor), encoding="utf-8")
    return tmp_path


def test_a_descriptor_declares_fields_for_its_own_kind(tmp_path: Path) -> None:
    catalog = load_catalog(
        _descriptor(tmp_path, appointmentKindFields={"health.visit": list(FIELDS)})
    )
    assert kind_fields_for(("core.health",), catalog) == {"health.visit": tuple(FIELDS)}
    assert kind_fields_for((), catalog) == {}


def test_fields_for_a_kind_the_module_does_not_add_are_refused(tmp_path: Path) -> None:
    with pytest.raises(CompositionError, match="health.other"):
        load_catalog(_descriptor(tmp_path, appointmentKindFields={"health.other": list(FIELDS)}))


def test_a_consent_is_refused_in_a_descriptor(tmp_path: Path) -> None:
    consent = {"key": "ok", "type": "consent", "mandatory": True, "labels": {"pl": "Zgoda"}}
    with pytest.raises(CompositionError, match="zgod"):
        load_catalog(_descriptor(tmp_path, appointmentKindFields={"health.visit": [consent]}))


def test_no_core_module_declares_kind_fields() -> None:
    assert kind_fields_for(tuple(settings.MODULE_CATALOG), settings.MODULE_CATALOG) == {}
