"""Marketing consents (ADR-073 §9, the owner's answers of 04.10): one
sentence that names the company, the list of who agreed read from the consent
journal — when, on which form, to which words — and a withdrawal written as
the journal's next line, never as a change."""

from __future__ import annotations

from typing import Any
from uuid import uuid7

import pytest
from django.db import DatabaseError, transaction
from rest_framework.exceptions import NotFound

from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
    Role,
    RoleScope,
)
from saas_core.modules.shared.customers.api import (
    MARKETING_WORDING,
    ConsentKind,
    Customer,
    current_document,
    marketing_wording,
    record_consent,
    strip_customer,
)
from saas_core.modules.shared.customers.consents import (
    ConsentChanged,
    list_marketing_consents,
    withdraw_marketing_consent,
)
from saas_core.modules.shared.customers.models import ConsentRecord
from test_booking import membership, tenant
from test_customers_documents import PRIVACY, approved, with_second_factor
from test_organization_lifecycle import authenticated_member, csrf_value

pytestmark = pytest.mark.django_db

BOOKING = "booking.appointment"


def person(member: Membership, name: str) -> Customer:
    return Customer.all_objects.create(
        organization_id=member.organization_id,
        display_name=name,
        email=f"{name.split()[0].lower()}@example.test",
        phone="600100200",
        contact_hash=name.ljust(64, "0")[:64],
    )


def agree(customer: Customer, *, locale: str = "pl", wording: str | None = None) -> ConsentRecord:
    """As a booking form does: the sentence shown is the wording written."""
    company = Organization.objects.values_list("name", flat=True).get(pk=customer.organization_id)
    return record_consent(
        customer=customer,
        kind=ConsentKind.MARKETING,
        wording=marketing_wording(locale, company) if wording is None else wording,
        locale=locale,
        source=BOOKING,
        source_reference=str(uuid7()),
    )


def test_the_sentence_names_the_company_in_the_forms_language() -> None:
    assert marketing_wording("pl", "Studio Fala") == (
        "Chcę otrzymywać oferty i promocje od Studio Fala e-mailem."
    )
    assert marketing_wording("de", "Studio Fala").startswith("Ich möchte Angebote")
    # A language without its own sentence has none: nothing is asked for.
    assert marketing_wording("es", "Studio Fala") == ""
    assert set(MARKETING_WORDING) == {"pl", "en", "de"}


def test_the_list_says_who_agreed_when_on_which_form_and_to_which_words() -> None:
    owner = with_second_factor(membership("zgody-lista"))
    approved(owner)
    with tenant(owner):
        anna, jan, ewa = (person(owner, name) for name in ("Anna Lis", "Jan Kot", "Ewa Sowa"))
        first = agree(anna)
        second = agree(jan, locale="de")
        # Accepting a document is another kind of line: not a marketing consent.
        document = current_document(PRIVACY, "pl")
        assert document is not None
        record_consent(customer=ewa, text_id=document.text_id, source=BOOKING, source_reference="x")
        listed = list_marketing_consents()
        nobody = list_marketing_consents(state="withdrawn")

    # Newest first, one row a person.
    assert [item["name"] for item in listed["items"]] == ["Jan Kot", "Anna Lis"]
    assert (listed["total"], listed["page"], listed["page_size"]) == (2, 1, 25)
    newest, oldest = listed["items"]
    assert oldest == {
        "customer_id": anna.id,
        "name": "Anna Lis",
        "email": "anna@example.test",
        "phone": "600100200",
        "granted": True,
        "consent_id": first.id,
        "consented_at": first.created_at,
        "source": BOOKING,
        "source_reference": first.source_reference,
        "locale": "pl",
        "wording": "Chcę otrzymywać oferty i promocje od zgody-lista e-mailem.",
        "withdrawn_at": None,
    }
    # The journal keeps the hash; the words come back from the constant.
    assert first.text_hash and "zgody-lista" in oldest["wording"]
    assert (newest["consent_id"], newest["locale"]) == (second.id, "de")
    assert newest["wording"].startswith("Ich möchte Angebote")
    assert nobody["items"] == [] and nobody["total"] == 0


def test_words_the_constant_no_longer_gives_are_said_to_be_unknown() -> None:
    owner = membership("zgody-nieznane")
    with tenant(owner):
        anna = person(owner, "Anna Lis")
        agree(anna, wording="Zgadzam się na newsletter.")
        renamed = person(owner, "Jan Kot")
        agree(renamed)
        Organization.objects.filter(pk=owner.organization_id).update(name="Nowa Nazwa")
        listed = list_marketing_consents()

    # Still listed as agreed, with the date and the form — only the exact
    # words cannot be shown any more.
    assert [(item["name"], item["wording"]) for item in listed["items"]] == [
        ("Jan Kot", ""),
        ("Anna Lis", ""),
    ]
    assert all(item["granted"] for item in listed["items"])


def test_a_withdrawal_is_the_journals_next_line_and_never_a_change() -> None:
    owner = membership("zgody-wycofanie")
    with tenant(owner):
        anna = person(owner, "Anna Lis")
        given = agree(anna)
        before = ConsentRecord.all_objects.count()
        done = withdraw_marketing_consent(anna.id, consent_id=given.id)
        lines = list(ConsentRecord.all_objects.filter(customer=anna).order_by("created_at", "id"))
        audit = OrganizationAuditEntry.objects.get(action="customers.consent.withdrawn")
        standing = list_marketing_consents()
        withdrawn = list_marketing_consents(state="withdrawn")

        # A repeat names a consent that is no longer the latest line.
        with pytest.raises(ConsentChanged):
            withdraw_marketing_consent(anna.id, consent_id=given.id)
        assert ConsentRecord.all_objects.count() == before + 1

    consent, withdrawal = lines
    assert (consent.id, consent.granted) == (given.id, True)
    assert (withdrawal.kind, withdrawal.granted) == ("marketing", False)
    assert (withdrawal.source, withdrawal.source_reference) == ("customers.panel", str(given.id))
    assert done["granted"] is False and done["withdrawn_at"] == withdrawal.created_at
    # The row still shows what was agreed to and when.
    assert (done["consent_id"], done["consented_at"]) == (given.id, given.created_at)
    assert done["wording"].startswith("Chcę otrzymywać oferty")
    assert standing["items"] == [] and [item["name"] for item in withdrawn["items"]] == ["Anna Lis"]
    # The history says who wrote it down — and never names the customer.
    assert (audit.target_type, audit.target_id, audit.actor_user_id) == (
        "customer",
        anna.id,
        owner.user_id,
    )
    assert audit.metadata == {"kind": "marketing", "consent_id": str(given.id)}

    # The database refuses a rewrite of the journal, whoever asks.
    with tenant(owner), pytest.raises(DatabaseError), transaction.atomic():
        ConsentRecord.all_objects.filter(pk=given.id).update(granted=False)


def test_a_customer_who_agrees_again_stands_as_agreed_and_a_stale_click_writes_nothing() -> None:
    owner = membership("zgody-ponownie")
    with tenant(owner):
        anna = person(owner, "Anna Lis")
        first = agree(anna)
        withdraw_marketing_consent(anna.id, consent_id=first.id)
        again = agree(anna, locale="en")
        (row,) = list_marketing_consents()["items"]
        # The list somebody opened before she agreed again names the old line.
        with pytest.raises(ConsentChanged):
            withdraw_marketing_consent(anna.id, consent_id=first.id)
        count = ConsentRecord.all_objects.filter(customer=anna).count()

    assert (row["granted"], row["consent_id"], row["locale"]) == (True, again.id, "en")
    assert row["withdrawn_at"] is None and count == 3


def test_reading_and_withdrawing_follow_the_customers_permissions() -> None:
    owner = membership("zgody-uprawnienia")
    stranger = membership("zgody-obca")
    with tenant(owner):
        anna = person(owner, "Anna Lis")
        given = agree(anna)
    role = Role.objects.create(
        key="czytelnik",
        organization=owner.organization,
        name="Czytelnik",
        scope=RoleScope.ORGANIZATION,
        permissions=["customers.read"],
    )
    Membership.objects.filter(pk=owner.pk).update(role=role)
    reader = Membership.objects.select_related("role", "organization", "user").get(pk=owner.pk)

    with tenant(reader):
        assert [item["name"] for item in list_marketing_consents()["items"]] == ["Anna Lis"]
        with pytest.raises(OrganizationPermissionDenied):
            withdraw_marketing_consent(anna.id, consent_id=given.id)
    Role.objects.filter(pk=role.pk).update(permissions=[])
    nobody = Membership.objects.select_related("role", "organization", "user").get(pk=owner.pk)
    with tenant(nobody), pytest.raises(OrganizationPermissionDenied):
        list_marketing_consents()

    # Another company neither sees her nor can withdraw for her.
    with tenant(stranger):
        assert list_marketing_consents()["items"] == []
        with pytest.raises(NotFound):
            withdraw_marketing_consent(anna.id, consent_id=given.id)


def test_a_customer_whose_data_was_removed_is_not_listed_and_the_journal_stays() -> None:
    owner = membership("zgody-usuniety")
    with tenant(owner):
        anna = person(owner, "Anna Lis")
        given = agree(anna)
        strip_customer(Customer.all_objects.select_for_update().get(pk=anna.id))
        listed = list_marketing_consents()
        with pytest.raises(NotFound):
            withdraw_marketing_consent(anna.id, consent_id=given.id)
        kept = ConsentRecord.all_objects.filter(pk=given.id).exists()

    assert listed["items"] == [] and listed["total"] == 0
    assert kept


def test_the_list_is_read_a_page_at_a_time() -> None:
    owner = membership("zgody-strony")
    with tenant(owner):
        for index in range(3):
            agree(person(owner, f"Klient{index} Testowy"))
        first = list_marketing_consents(page=1, page_size=2)
        rest = list_marketing_consents(page=2, page_size=2)

    assert (first["total"], len(first["items"]), len(rest["items"])) == (3, 2, 1)
    assert first["items"][0]["name"] == "Klient2 Testowy"
    assert rest["items"][0]["name"] == "Klient0 Testowy"


def test_the_panel_lists_and_withdraws_over_the_api() -> None:
    _, owner, client = authenticated_member(
        email="zgody-api@example.test", role_key="owner", slug="zgody-api"
    )
    with tenant(owner):
        anna = person(owner, "Anna Lis")
        given = agree(anna)
    url = "/api/v1/customers/consents/marketing/"

    def send(body: dict[str, Any]) -> Any:
        return client.post(
            f"{url}{anna.id}/withdraw/", body, format="json", HTTP_X_CSRFTOKEN=csrf_value(client)
        )

    listed = client.get(url)
    assert listed.status_code == 200, listed.data
    (row,) = listed.json()["items"]
    assert (row["name"], row["email"], row["granted"], row["source"]) == (
        "Anna Lis",
        "anna@example.test",
        True,
        BOOKING,
    )
    assert row["consent_id"] == str(given.id)
    assert client.get(f"{url}?state=other").status_code == 400
    assert client.post(f"{url}{anna.id}/withdraw/", {}, format="json").status_code == 403  # CSRF
    assert send({}).status_code == 400

    done = send({"consent_id": row["consent_id"]})
    assert done.status_code == 200, done.data
    assert (done.json()["granted"], done.json()["withdrawn_at"] is not None) == (False, True)
    again = send({"consent_id": row["consent_id"]})
    assert (again.status_code, again.json()["code"]) == (409, "consent_changed")
    assert client.get(url).json()["items"] == []
    (gone,) = client.get(f"{url}?state=withdrawn").json()["items"]
    assert gone["customer_id"] == str(anna.id)
