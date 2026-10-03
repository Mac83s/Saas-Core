"""`shared.customers` (ADR-073 §2): the company's customer is a record of its
own module, on the table booking made, and whoever stores something about a
customer says how it goes when the customer is stripped."""

from __future__ import annotations

import pytest
from django.apps import apps
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from saas_core.modules.shared.booking.models import Appointment
from saas_core.modules.shared.booking.services import anonymize_customer
from saas_core.modules.shared.customers import services
from saas_core.modules.shared.customers.api import (
    CUSTOMER_MODEL,
    Customer,
    match_or_create,
    register_customer_anonymizer,
    strip_customer,
)
from test_booking import catalog, create, membership, tenant

pytestmark = pytest.mark.django_db(transaction=True)


def test_the_customer_is_a_model_of_customers_on_the_table_booking_made() -> None:
    assert apps.get_model(CUSTOMER_MODEL) is Customer
    assert Customer._meta.db_table == "booking_customer"
    assert Appointment._meta.get_field("customer").related_model is Customer
    with pytest.raises(LookupError):
        apps.get_model("booking", "Customer")


@pytest.mark.parametrize(
    "node", [("customers", "0001_customer_state"), ("booking", "0029_customer_to_customers")]
)
def test_the_move_is_state_only_in_both_directions(node: tuple[str, str]) -> None:
    """Nothing is copied and nothing is renamed: neither migration sends a
    statement to the database, forwards or backwards — so a rollback past
    them needs no data to be put back."""
    loader = MigrationLoader(connection)
    migration = loader.graph.nodes[node]
    for backwards in (False, True):
        statements = loader.collect_sql([(migration, backwards)])
        assert [line for line in statements if line and not line.startswith("--")] == []


def test_booking_says_what_a_visit_keeps_of_a_customer() -> None:
    owner = membership("klienci-wizyty")
    booked = create(owner, catalog(owner), key="visit-1").appointment
    with tenant(owner):
        Appointment.all_objects.filter(pk=booked.id).update(
            customer_notes="Boli mnie kolano", place_address="ul. Polna 3"
        )
        anonymize_customer(booked.customer_id)
        visit = Appointment.all_objects.get(pk=booked.id)
        person = Customer.all_objects.get(pk=booked.customer_id)

    assert "shared.booking.visits" in services._anonymizers
    assert (person.display_name, person.email, person.phone) == ("Zanonimizowany klient", "", "")
    assert person.anonymized_at is not None
    assert (visit.customer_notes, visit.place_address) == ("", "")


def test_every_registered_module_is_called_with_the_stripped_customer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = membership("klienci-rejestr")
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(services, "_anonymizers", {})
    register_customer_anonymizer("b.second", lambda person: seen.append(("b", person.email)))
    register_customer_anonymizer("a.first", lambda person: seen.append(("a", person.email)))

    with tenant(owner):
        person, email = match_or_create(
            owner.organization,
            {"display_name": "Ewa Nowak", "email": " Ewa@Example.test ", "phone": ""},
        )
        again, _ = match_or_create(
            owner.organization, {"display_name": "Ewa", "email": "ewa@example.test"}
        )
        strip_customer(person)
        after, _ = match_or_create(
            owner.organization, {"display_name": "Ewa Nowak", "email": "ewa@example.test"}
        )

    assert email == "ewa@example.test"
    assert again.id == person.id
    # In the order of their names, each after the row itself was stripped.
    assert seen == [("a", ""), ("b", "")]
    # Whoever comes back with the same contact is a new customer.
    assert after.id != person.id
