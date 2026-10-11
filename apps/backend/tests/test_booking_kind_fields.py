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


def test_the_kinds_fields_go_after_the_fields_a_service_already_has() -> None:
    """A preset sets no kind, so the preset road copies nothing; what the helper
    guarantees is the position: the kind's fields follow whatever the service
    already has (here a preset offer's, given a kind by hand)."""
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
    assert output.rstrip().endswith("Usługi: 2, dodane pola: 4, odmowy: 0.")
    assert "dodałbym Liczba sztuk, Notatka" in output
    assert (_count(first), _count(second)) == (0, 0)


def test_apply_adds_and_a_second_run_adds_nothing() -> None:
    owner = membership("kf-apply")
    first, _plain = _bare_services(owner, "Alpha", "Beta")
    _run("--apply", organization=str(owner.organization_id))
    assert asked(owner, first) == EXPECTED
    again = _run("--apply", organization=str(owner.organization_id))
    assert again.rstrip().endswith("Usługi: 0, dodane pola: 0, odmowy: 0.")
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
    assert output.rstrip().endswith("Usługi: 1, dodane pola: 1, odmowy: 0.")
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


def _many_services_one_full(owner: Any) -> tuple[Service, Service]:
    """Two services of the kind: one with 20 active fields (no room), one bare."""
    full, bare = _bare_services(owner, "Full", "Bare")
    with tenant(owner):
        for number in range(20):
            FormField.all_objects.create(
                organization=owner.organization,
                service=full,
                name=f"Pole {number}",
                position=number + 1,
            )
    return full, bare


def test_a_refused_service_is_reported_and_the_run_goes_on() -> None:
    owner = membership("kf-refuse")
    full, bare = _many_services_one_full(owner)
    dry = StringIO()
    with pytest.raises(CommandError, match="Odmowy: 1"):
        call_command("booking_apply_kind_fields", stdout=dry)
    assert "Full: odmowa (fields_too_many)" in dry.getvalue()
    assert dry.getvalue().rstrip().endswith("Usługi: 1, dodane pola: 2, odmowy: 1.")
    assert (_count(full), _count(bare)) == (20, 0)
    out = StringIO()
    with pytest.raises(CommandError, match="Odmowy: 1"):
        call_command("booking_apply_kind_fields", "--apply", stdout=out)
    assert "Full: odmowa (fields_too_many)" in out.getvalue()
    # The refused service is untouched, the other one was written.
    assert (_count(full), _count(bare)) == (20, 2)


def test_two_declared_fields_with_one_label_are_refused_for_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twin = ({**FIELDS[0]}, {**FIELDS[1], "labels": {"pl": " liczba SZTUK ", "en": "Other"}})
    monkeypatch.setattr(settings, "APPOINTMENT_KIND_FIELDS", {KIND: twin}, raising=False)
    owner = membership("kf-twin")
    (service,) = _bare_services(owner, "Alpha")
    with pytest.raises(CommandError, match="Odmowy: 1"):
        _run("--apply", organization=str(owner.organization_id))
    assert _count(service) == 0


def test_a_label_with_outer_spaces_counts_as_there(monkeypatch: pytest.MonkeyPatch) -> None:
    padded = ({**FIELDS[0], "labels": {"pl": "  Liczba sztuk ", "en": "Count"}},)
    monkeypatch.setattr(settings, "APPOINTMENT_KIND_FIELDS", {KIND: padded}, raising=False)
    owner = membership("kf-pad")
    (service,) = _bare_services(owner, "Alpha")
    _run("--apply", organization=str(owner.organization_id))
    assert (
        _run("--apply", organization=str(owner.organization_id))
        .rstrip()
        .endswith("Usługi: 0, dodane pola: 0, odmowy: 0.")
    )
    assert _count(service) == 1


def test_a_run_without_declarations_stops_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "APPOINTMENT_KIND_FIELDS", {}, raising=False)
    output = _run()
    assert output.strip() == "Żaden moduł nie deklaruje pól dla typów wizyty."


def test_apply_under_a_role_that_does_not_own_the_tables() -> None:
    """The test connection owns its tables and so skips row-level security; the
    app's role does not. `SET ROLE` to a plain one, as the SEO test does."""
    from psycopg import sql  # noqa: PLC0415

    mine, other = membership("kf-role-a"), membership("kf-role-b")
    (mine_service,) = _bare_services(mine, "Alpha")
    (other_service,) = _bare_services(other, "Beta")
    role = sql.Identifier("saas_core_kf_probe")
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(role))
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        cursor.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
            ).format(role)
        )
        cursor.execute(
            sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role)
        )
        try:
            cursor.execute(sql.SQL("SET ROLE {}").format(role))
            cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
            assert cursor.fetchone() == (False, False)
            _run("--apply", organization=str(mine.organization_id))
            # (The un-narrowed run reads the company list on the pre-tenant
            # connection, which does not see a test's uncommitted rows.)
        finally:
            cursor.execute("RESET ROLE")
        assert (_count(mine_service), _count(other_service)) == (2, 0)
        cursor.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role))
        cursor.execute(sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(role))
        cursor.execute(sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(role))
        cursor.execute(sql.SQL("DROP ROLE {}").format(role))


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


def _declared(tmp_path: Path, *fields: dict[str, Any]) -> Any:
    return load_catalog(_descriptor(tmp_path, appointmentKindFields={"health.visit": list(fields)}))


def test_boot_refuses_an_unknown_type_a_thin_choice_and_twin_labels(tmp_path: Path) -> None:
    base = {"key": "x", "mandatory": False, "labels": {"pl": "X", "en": "X"}}
    with pytest.raises(CompositionError, match="rodzaj pola"):
        _declared(tmp_path, {**base, "type": "slider"})
    one = [{"key": "a", "labels": {"pl": "A", "en": "A"}}]
    with pytest.raises(CompositionError, match="od 2 do 20"):
        _declared(tmp_path, {**base, "type": "choice", "options": one})
    long = {"key": "b", "labels": {"pl": "B" * 81, "en": "B"}}
    with pytest.raises(CompositionError, match="za długą"):
        _declared(tmp_path, {**base, "type": "choice", "options": [*one, long]})
    with pytest.raises(CompositionError, match="powtórzon"):
        _declared(
            tmp_path,
            {**base, "type": "text"},
            {**base, "key": "y", "type": "text", "labels": {"pl": " x ", "en": "Y"}},
        )


def test_form_field_save_v1_still_runs_and_binds_the_team() -> None:
    """ADR-076 §1: a plan that holds @1 across the deploy must still run."""
    from types import SimpleNamespace  # noqa: PLC0415

    from saas_core.modules.shared.booking.field_commands import (  # noqa: PLC0415
        FIELD_SAVE,
        FIELD_SAVE_V1,
    )

    owner = membership("kf-v1")
    service = made(owner, "Alpha", kind="")
    assert FIELD_SAVE_V1.version == 1 and FIELD_SAVE.version == 2
    assert "mandatory_for_staff" not in FIELD_SAVE_V1.input_schema["properties"]
    old = {
        "field_id": None,
        "service_id": str(service.id),
        "name": "Numer",
        "kind": "text",
        "options": None,
        "mandatory": True,
        "position": None,
        "active": None,
    }
    with tenant(owner) as context:
        call = SimpleNamespace(
            context=context, idempotency_key=key(), preview=SimpleNamespace(observed_versions={})
        )
        saved = FIELD_SAVE_V1.run(old, call)
        assert saved["mandatory"] is True and saved["mandatory_for_staff"] is True
        # A later change through @1 leaves the team switch as the company set it.
        FormField.all_objects.filter(pk=saved["field_id"]).update(mandatory_for_staff=False)
        call.preview.observed_versions = {
            f"booking.form_field:{saved['field_id']}": saved["version"]
        }
        changed = FIELD_SAVE_V1.run({**old, "field_id": saved["field_id"], "mandatory": None}, call)
        assert changed["mandatory_for_staff"] is False


def test_no_core_module_declares_kind_fields() -> None:
    # A product's own module may declare them (ADR-049); the core's never do.
    own = tuple(
        key for key, module in settings.MODULE_CATALOG.items() if module.layer in {"core", "shared"}
    )
    assert kind_fields_for(own, settings.MODULE_CATALOG) == {}
