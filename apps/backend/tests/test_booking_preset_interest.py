"""Presets by hand (ADR-072, „Rozstrzygnięcia plastra 5g”): the panel starts an
offer from a ready preset over the API — the same write the assistant's
command makes — and a company signs up for a preset that is announced and not
ready yet, saying what it lacks; the platform reads who waits, one company at
a time."""

from __future__ import annotations

from collections.abc import Iterator
from io import StringIO
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.erasure import erase_organization
from saas_core.modules.core.organizations.models import Membership, Organization
from saas_core.modules.shared.booking import presets
from saas_core.modules.shared.booking.models import PresetInterest, Service
from test_organization_lifecycle import authenticated_member
from test_team_people import bookable, member_of
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db

SOON = "core.hourly_space"
APPLY = "/api/v1/booking/presets/apply/"


@pytest.fixture(autouse=True)
def fresh() -> Iterator[None]:
    cache.clear()
    presets._catalogue.cache_clear()
    yield
    presets._catalogue.cache_clear()


def company(slug: str) -> tuple[Membership, APIClient]:
    _, owner, _ = authenticated_member(email=f"{slug}@example.test", role_key="owner", slug=slug)
    bookable(owner.organization)
    return owner, authenticated_client(owner)


def key() -> dict[str, str]:
    return {"HTTP_IDEMPOTENCY_KEY": uuid4().hex}


def listed(client: APIClient) -> dict[str, Any]:
    answer = client.get("/api/v1/booking/presets/")
    assert answer.status_code == 200, answer.content
    return {item["id"]: item for item in answer.json()["presets"]}


def codes(answer: Any) -> list[tuple[str | None, str]]:
    return [(error["field"], error["code"]) for error in answer.json()["errors"]]


def test_the_panel_starts_an_offer_from_a_ready_preset() -> None:
    owner, client = company("wzorce-reczne")
    stay = {"preset_id": "core.lodging", "name": "Domek nad jeziorem"}

    # Checked first, nothing saved.
    preview = client.post(f"{APPLY}preview/", stay, format="json")
    assert preview.status_code == 200, preview.content
    assert preview.json()["name"] == "Domek nad jeziorem"
    assert not Service.all_objects.filter(organization=owner.organization).exists()

    once = key()
    made = client.post(APPLY, stay, format="json", **once)
    assert made.status_code == 201, made.content
    offer = made.json()
    assert (offer["name"], offer["time_model"], offer["active"]) == (
        "Domek nad jeziorem",
        "range",
        False,
    )
    assert (offer["preset_id"], offer["preset_version"]) == ("core.lodging", 5)
    # The same key again answers the same offer; another key makes a second.
    again = client.post(APPLY, stay, format="json", **once)
    assert (again.status_code, again.json()["id"]) == (201, offer["id"])
    assert Service.all_objects.filter(organization=owner.organization).count() == 1

    # A visit needs its length, and a preset that is only announced is refused
    # on its field — as the assistant's command is.
    visit = client.post(
        APPLY, {"preset_id": "core.specialist_visit", "name": "Konsultacja"}, format="json", **key()
    )
    assert visit.status_code == 400 and ("duration_minutes", "required") in codes(visit)
    soon = client.post(APPLY, {"preset_id": SOON, "name": "Kort"}, format="json", **key())
    assert soon.status_code == 400 and codes(soon) == [("preset_id", "preset_not_ready")]
    unknown = client.post(APPLY, {"preset_id": "core.nie_ma", "name": "X"}, format="json", **key())
    assert codes(unknown) == [("preset_id", "preset_unknown")]
    assert client.post(APPLY, stay, format="json").status_code == 400  # no key

    # Whoever does not set services up starts nothing.
    worker = authenticated_client(member_of(owner, "wzorce-reczne-osoba@example.test", "staff"))
    assert worker.post(APPLY, stay, format="json", **key()).status_code == 403
    assert Service.all_objects.filter(organization=owner.organization).count() == 1


def test_a_company_signs_up_for_a_preset_that_is_not_ready_and_says_what_it_lacks() -> None:
    owner, client = company("wzorce-wkrotce")
    address = f"/api/v1/booking/presets/{SOON}/interest/"
    assert listed(client)[SOON]["interest"] is None

    saved = client.put(
        address, {"note": "  Kort na godziny, z ceną w szczycie.  "}, format="json", **key()
    )
    assert saved.status_code == 200, saved.content
    assert saved.json() == {
        "preset_id": SOON,
        "note": "Kort na godziny, z ceną w szczycie.",
        "created_at": saved.json()["created_at"],
        "updated_at": saved.json()["updated_at"],
    }
    row = PresetInterest.all_objects.get(organization=owner.organization)
    assert (row.preset_id, row.preset_version, row.created_by) == (SOON, 1, owner.user_id)
    # The list says so beside that preset, and beside no other.
    signed = listed(client)
    assert signed[SOON]["interest"]["note"] == "Kort na godziny, z ceną w szczycie."
    assert [name for name, item in signed.items() if item["interest"]] == [SOON]

    # Signing up again rewrites the note: one row per company and preset. The
    # note may be empty; a key reused for other words is refused.
    once = key()
    assert client.put(address, {"note": ""}, format="json", **once).json()["note"] == ""
    assert client.put(address, {"note": ""}, format="json", **once).status_code == 200
    conflict = client.put(address, {"note": "Inaczej"}, format="json", **once)
    assert (conflict.status_code, conflict.json()["code"]) == (409, "booking_idempotency_conflict")
    assert PresetInterest.all_objects.filter(organization=owner.organization).count() == 1

    # A ready preset is used, not waited for; a made-up one is no preset; a
    # note has a limit.
    ready = client.put(
        "/api/v1/booking/presets/core.lodging/interest/", {"note": ""}, format="json", **key()
    )
    assert ready.status_code == 400 and codes(ready) == [("preset_id", "preset_ready")]
    made_up = client.put(
        "/api/v1/booking/presets/core.nie_ma/interest/", {"note": ""}, format="json", **key()
    )
    assert made_up.status_code == 404
    long = client.put(address, {"note": "x" * 1001}, format="json", **key())
    assert long.status_code == 400 and codes(long) == [("note", "max_length")]

    # Another company's list is its own.
    _, other = company("wzorce-wkrotce-inna")
    assert listed(other)[SOON]["interest"] is None
    worker = authenticated_client(member_of(owner, "wzorce-wkrotce-osoba@example.test", "staff"))
    assert worker.put(address, {"note": "x"}, format="json", **key()).status_code == 403
    assert worker.delete(address).status_code == 403

    # Withdrawn: gone from the list; a repeat changes nothing.
    assert client.delete(address).status_code == 204
    assert listed(client)[SOON]["interest"] is None
    assert client.delete(address).status_code == 204
    assert not PresetInterest.all_objects.filter(organization=owner.organization).exists()


def test_the_platform_reads_who_waits_one_company_at_a_time() -> None:
    def said() -> str:
        out = StringIO()
        call_command("booking_preset_interest", stdout=out)
        return out.getvalue()

    assert said().strip() == "Nikt nie czeka."

    owner, client = company("wzorce-lista-czeka")
    _, other = company("wzorce-lista-czeka-druga")
    for who, preset_id, note in (
        (client, SOON, "Kort\nna godziny"),
        (other, SOON, ""),
        (other, "core.group_class", "Karnety"),
    ):
        answer = who.put(
            f"/api/v1/booking/presets/{preset_id}/interest/", {"note": note}, format="json", **key()
        )
        assert answer.status_code == 200, answer.content

    statements: list[str] = []

    def record(execute: Any, sql: str, params: Any, many: bool, context: Any) -> Any:
        statements.append(sql)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(record):
        report = said()
    lines = report.splitlines()
    # The most awaited first; each company with what it wrote, on one line.
    assert lines[0] == f"{SOON}: 2" and lines[3] == "core.group_class: 1"
    assert f"{owner.organization.name} ({owner.organization_id}): Kort na godziny" in lines[1]
    assert lines[2].endswith(": —") and lines[4].endswith(": Karnety")
    # Under row-level security a read across companies returns nothing: the
    # tenant is set before each company's rows are read.
    reads = [i for i, sql in enumerate(statements) if "booking_presetinterest" in sql]
    sets = [i for i, sql in enumerate(statements) if "app.organization_id" in sql]
    assert reads and all(any(at < read for at in sets) for read in reads)
    assert len(sets) >= len(reads)

    out = StringIO()
    call_command("booking_preset_interest", preset="core.group_class", stdout=out)
    assert out.getvalue().splitlines()[0] == "core.group_class: 1" and SOON not in out.getvalue()


def test_erasing_the_company_takes_its_sign_ups() -> None:
    owner, client = company("wzorce-usuniecie")
    address = f"/api/v1/booking/presets/{SOON}/interest/"
    assert client.put(address, {"note": "Sala"}, format="json", **key()).status_code == 200
    organization_id = owner.organization_id

    erase_organization(organization=owner.organization, requested_by=None, reason="test")

    assert not PresetInterest.all_objects.filter(organization_id=organization_id).exists()
    assert not Organization.objects.filter(pk=organization_id).exists()
