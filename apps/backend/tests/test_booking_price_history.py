"""The record of prices (ADR-072 §6; ADR-073, slice 4i): every write of a
price appends a line nobody can change, and the price list of a past day is
read back from those lines — not from the audit."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.organizations.erasure import erase_organization
from saas_core.modules.shared.booking.models import PriceHistoryEntry, PriceRule, Service
from saas_core.modules.shared.booking.price_history import recorded_since, rules_at
from saas_core.modules.shared.booking.prices import (
    copy_prices_to_next_year,
    delete_price,
    list_price_changes,
    price_for,
    price_list_on,
    save_price,
)
from saas_core.modules.shared.booking.setup import discard_draft, save_service
from test_booking import catalog, membership, tenant
from test_booking_prices import add, cottages, key, price, season
from test_organization_lifecycle import authenticated_member
from test_team_people import bookable

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_throttles() -> None:
    cache.clear()


def moment(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@contextmanager
def at(monkeypatch: pytest.MonkeyPatch, text: str) -> Iterator[datetime]:
    """The clock stands at `text` (UTC) while a price is written."""
    fixed = moment(text)
    with monkeypatch.context() as patched:
        patched.setattr(timezone, "now", lambda: fixed)
        yield fixed


def lines(owner: Any) -> list[PriceHistoryEntry]:
    return list(
        PriceHistoryEntry.all_objects.filter(organization=owner.organization).order_by(
            "recorded_at", "id"
        )
    )


def test_every_write_of_a_price_leaves_a_line_and_a_preview_leaves_none() -> None:
    owner = membership("historia-zapis")
    service = catalog(owner)["service"]
    with tenant(owner):
        save_price(price_id=None, data=price(12000, service_id=service.id), preview=True)
        assert lines(owner) == []

        made = save_price(
            price_id=None, data=price(12000, service_id=service.id), idempotency_key="cena-1"
        )
        # The same key again writes nothing, so it records nothing.
        save_price(
            price_id=None, data=price(12000, service_id=service.id), idempotency_key="cena-1"
        )
        save_price(
            price_id=made.item_id,
            data={"amount_minor": 15000},
            expected_version=1,
            preview=True,
        )
        save_price(
            price_id=made.item_id,
            data={"amount_minor": 15000},
            expected_version=1,
            idempotency_key=key(),
        )
        # A save that changes nothing is no change of the price.
        save_price(
            price_id=made.item_id,
            data={"amount_minor": 15000},
            expected_version=2,
            idempotency_key=key(),
        )
        save_price(
            price_id=made.item_id,
            data={"active": False},
            expected_version=2,
            idempotency_key=key(),
        )
        delete_price(price_id=made.item_id, expected_version=3, idempotency_key=key())
        written = lines(owner)

    assert [
        (line.change, line.previous_amount_minor, line.amount_minor, line.state["active"])
        for line in written
    ] == [
        ("created", None, 12000, True),
        ("updated", 12000, 15000, True),
        ("updated", 15000, 15000, False),
        ("deleted", 15000, 15000, False),
    ]
    assert {line.rule_id for line in written} == {made.item_id}
    assert {(line.actor_id, line.acting_via, line.currency) for line in written} == {
        (owner.user_id, "", "PLN")
    }
    # The whole rule, by column: what `price_for` needs to answer again.
    assert written[0].state["service_id"] == str(service.id)
    assert (written[0].state["basis"], written[0].state["version"]) == ("per_booking", 1)
    assert not PriceRule.all_objects.filter(organization=owner.organization).exists()


def test_copies_for_next_year_and_a_discarded_draft_are_in_the_record() -> None:
    owner = membership("historia-kopie")
    configured = cottages(owner)
    with tenant(owner):
        add(40000, "per_time_unit", service_id=configured["stay"].id)
        add(
            50000,
            "per_time_unit",
            service_id=configured["stay"].id,
            **season("2026-07-01", "2026-08-31"),
        )
        copy_prices_to_next_year(year=2026, preview=True)
        assert len(lines(owner)) == 2
        copy_prices_to_next_year(year=2026, idempotency_key=key())
        copied = lines(owner)[2:]

        draft = save_service(
            service_id=None,
            data={
                "name": "Szkic",
                "time_model": "range",
                "range_unit": "night",
                "group_ids": [configured["group"].id],
            },
            idempotency_key=key(),
        ).value.service
        # As a preset leaves an offer: not switched on yet.
        Service.all_objects.filter(pk=draft.id).update(draft=True, active=False)
        add(9900, "per_time_unit", service_id=draft.id)
        discard_draft(service_id=draft.id, idempotency_key=key())
        after = lines(owner)

    assert [(line.change, line.state["starts_on"]) for line in copied] == [
        ("created", "2027-07-01")
    ]
    assert [(line.change, line.amount_minor) for line in after[-2:]] == [
        ("created", 9900),
        ("deleted", 9900),
    ]
    assert after[-1].state["service_id"] == str(draft.id)


def test_the_price_list_of_a_past_day_is_read_from_the_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = membership("historia-odczyt")
    configured = cottages(owner)
    stay = configured["stay"]
    with tenant(owner):
        with at(monkeypatch, "2026-03-01T10:00:00"):
            base = add(40000, "per_time_unit", service_id=stay.id)
        with at(monkeypatch, "2026-03-10T10:00:00"):
            july = add(
                60000,
                "per_time_unit",
                service_id=stay.id,
                **season("2026-07-01", "2026-07-31"),
            )
        with at(monkeypatch, "2026-04-02T08:00:00"):
            save_price(
                price_id=base.id,
                data={"amount_minor": 45000},
                expected_version=1,
                idempotency_key=key(),
            )
        with at(monkeypatch, "2026-05-05T12:00:00"):
            delete_price(price_id=july.id, expected_version=1, idempotency_key=key())

        def asked(when: str, day: str) -> int | None:
            then = rules_at(owner.organization_id, moment(when))
            found = price_for(then, day=date.fromisoformat(day), service_id=stay.id)
            return found.amount_minor if found else None

        with at(monkeypatch, "2026-06-01T09:00:00"):
            today = price_list_on(date(2026, 6, 1))
            march = price_list_on(date(2026, 3, 15))
            with pytest.raises(ValidationError) as early:
                price_list_on(date(2026, 2, 27))
            changes = list_price_changes()
            of_july = list_price_changes(price_id=july.id)

        # What the list said on a day, for a night in July and one in May.
        assert asked("2026-03-05T00:00:00", "2026-07-10") == 40000
        assert asked("2026-03-15T00:00:00", "2026-07-10") == 60000
        assert asked("2026-03-15T00:00:00", "2026-05-10") == 40000
        assert asked("2026-04-03T00:00:00", "2026-05-10") == 45000
        assert asked("2026-05-06T00:00:00", "2026-07-10") == 45000
        # Before the first line the record knows nothing — and says since when.
        assert rules_at(owner.organization_id, moment("2026-02-01T00:00:00")) == []
        assert recorded_since(owner.organization_id) == moment("2026-03-01T10:00:00")

    assert [(rule.id, rule.amount_minor) for rule in today["items"]] == [(base.id, 45000)]
    assert today["as_of"] == moment("2026-06-01T09:00:00")
    # The end of 15 March in Warsaw: both prices as they were, the old amount.
    assert march["as_of"] == moment("2026-03-15T23:00:00")
    assert [(rule.id, rule.amount_minor, rule.starts_on) for rule in march["items"]] == [
        (base.id, 40000, None),
        (july.id, 60000, date(2026, 7, 1)),
    ]
    restored = march["items"][1]
    assert (restored.service_id, restored.version, restored.created_at) == (
        stay.id,
        1,
        july.created_at,
    )
    assert early.value.get_codes() == {"day": ["before_price_history"]}
    assert (changes["total"], changes["recorded_since"]) == (4, moment("2026-03-01T10:00:00"))
    assert [
        (item["change"], item["previous_amount_minor"], item["amount_minor"])
        for item in changes["items"]
    ] == [
        ("deleted", 60000, 60000),
        ("updated", 40000, 45000),
        ("created", None, 60000),
        ("created", None, 40000),
    ]
    assert changes["items"][0]["actor"]["email"] == owner.user.email
    # A deleted price still has its lines, and they still say what it was.
    assert [item["change"] for item in of_july["items"]] == ["deleted", "created"]
    assert of_july["items"][0]["price"].starts_on == date(2026, 7, 1)


def test_a_line_is_never_changed_or_removed_except_with_its_company() -> None:
    owner = membership("historia-trwala")
    service = catalog(owner)["service"]
    with tenant(owner):
        add(12000, service_id=service.id)
        (line,) = lines(owner)
        for attempt in (
            lambda: PriceHistoryEntry.all_objects.filter(pk=line.pk).update(amount_minor=1),
            lambda: PriceHistoryEntry.all_objects.filter(pk=line.pk).delete(),
        ):
            with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
                attempt()
        assert [item.amount_minor for item in lines(owner)] == [12000]


def test_the_record_goes_with_the_company_when_the_company_is_erased() -> None:
    owner = membership("historia-usuniecie")
    service = catalog(owner)["service"]
    with tenant(owner):
        add(12000, service_id=service.id)
    organization_id = owner.organization_id

    erase_organization(organization=owner.organization, requested_by=None, reason="test")

    assert not PriceHistoryEntry.all_objects.filter(organization_id=organization_id).exists()


def test_the_baseline_of_the_migration_reads_like_a_line_written_by_the_service() -> None:
    """The migration writes `to_jsonb(rule)` for every price that exists; the
    service writes the same columns from the model. Both must restore."""
    owner = membership("historia-poczatek")
    stay = cottages(owner)["stay"]
    with tenant(owner):
        made = add(
            50000,
            "per_time_unit",
            service_id=stay.id,
            weekdays=[4, 5],
            **season("2026-07-01", "2026-08-31"),
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO booking_pricehistoryentry (id, organization_id, rule_id, change, "
                "state, amount_minor, previous_amount_minor, currency, actor_id, acting_via, "
                "recorded_at) SELECT gen_random_uuid(), rule.organization_id, rule.id, "
                "'baseline', to_jsonb(rule), rule.amount_minor, NULL, rule.currency, NULL, '', "
                "now() FROM booking_pricerule AS rule WHERE rule.id = %s",
                [made.id],
            )
        by_service, by_migration = (
            rule
            for rule in (
                rules_at(owner.organization_id, line.recorded_at)[0] for line in lines(owner)
            )
        )

    for name in (field.attname for field in PriceRule._meta.concrete_fields):
        assert getattr(by_migration, name) == getattr(by_service, name) == getattr(made, name)


def test_the_history_api_answers_management_and_refuses_the_others() -> None:
    _, owner, client = authenticated_member(
        email="historia-api@example.test", role_key="owner", slug="historia-api"
    )
    bookable(owner.organization)
    service = catalog(owner)["service"]
    with tenant(owner):
        made = add(12000, service_id=service.id, name="Cennik podstawowy")
        save_price(
            price_id=made.id,
            data={"amount_minor": 13000},
            expected_version=1,
            idempotency_key=str(uuid4()),
        )

    history = client.get("/api/v1/booking/setup/prices/history/", {"price_id": str(made.id)})
    today = client.get(
        "/api/v1/booking/setup/prices/on-day/", {"day": timezone.localdate().isoformat()}
    )
    early = client.get("/api/v1/booking/setup/prices/on-day/", {"day": "2020-01-01"})
    undated = client.get("/api/v1/booking/setup/prices/on-day/")

    assert history.status_code == 200, history.data
    body = history.json()
    assert [
        (item["change"], item["previous_amount_minor"], item["amount_minor"], item["currency"])
        for item in body["items"]
    ] == [("updated", 12000, 13000, "PLN"), ("created", None, 12000, "PLN")]
    assert body["items"][0]["price"]["name"] == "Cennik podstawowy"
    assert body["items"][0]["actor"]["email"] == "historia-api@example.test"
    assert today.status_code == 200, today.data
    assert [(item["id"], item["amount_minor"]) for item in today.json()["items"]] == [
        (str(made.id), 13000)
    ]
    assert early.status_code == 400
    assert [(error["field"], error["code"]) for error in early.json()["errors"]] == [
        ("day", "before_price_history")
    ]
    assert undated.status_code == 400

    _, _, worker = authenticated_member(
        email="historia-pracownik@example.test",
        role_key="staff",
        organization=owner.organization,
    )
    assert worker.get("/api/v1/booking/setup/prices/history/").status_code == 403
    assert (
        worker.get("/api/v1/booking/setup/prices/on-day/", {"day": "2026-10-04"}).status_code == 403
    )
