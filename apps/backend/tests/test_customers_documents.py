"""The company's documents for its customers and the consent journal
(ADR-073 §9): a draft binds nobody, a version is approved by a person with a
fresh second factor and is never rewritten, a reader gets the text in exactly
the language asked for, and the journal says who saw which row."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid7

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.test import APIClient

from saas_core.http.exceptions import problem_errors
from saas_core.modules.core.identity.models import UserMfaMethod
from saas_core.modules.core.identity.step_up import (
    StepUpMfaSetupRequired,
    StepUpRequired,
    activate_step_up,
)
from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.context import (
    acting_context,
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.erasure import erase_organization
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
    Role,
    RoleScope,
)
from saas_core.modules.core.organizations.person_gate import PersonRequired
from saas_core.modules.shared.customers.api import (
    Customer,
    current_document,
    record_consent,
)
from saas_core.modules.shared.customers.documents import (
    DocumentVersionConflict,
    add_text,
    approve_draft,
    list_documents,
    read_document,
    save_draft,
)
from saas_core.modules.shared.customers.models import (
    ConsentRecord,
    CustomerDocument,
    DocumentRoute,
    DocumentText,
    DocumentVersion,
)
from saas_core.modules.shared.customers.security import public_documents_context
from test_booking import membership, tenant
from test_sites_api import sites_client

pytestmark = pytest.mark.django_db

PRIVACY = "privacy_policy"
TEXT = "Administratorem danych jest Studio.\n\nDane przetwarzamy, żeby umówić wizytę."


def company(slug: str, locales: tuple[str, ...] = ("pl", "en")) -> Membership:
    owner = membership(slug)
    Organization.objects.filter(pk=owner.organization_id).update(public_locales=list(locales))
    owner.organization.refresh_from_db()
    return owner


def with_second_factor(member: Membership) -> Membership:
    UserMfaMethod.objects.create(
        user=member.user, secret_ciphertext="x", confirmed_at=timezone.now()
    )
    return member


def stepped_up() -> Any:
    return activate_step_up(int(timezone.now().timestamp()))


def approved(
    member: Membership, text: str = TEXT, kind: str = PRIVACY, **extra: Any
) -> dict[str, Any]:
    """A version a person approved from a draft in Polish."""
    with tenant(member), stepped_up():
        version = read_document(kind)["document"]["version"]
        saved = save_draft(kind, text=text, locale="pl", expected_version=version)
        return approve_draft(kind, expected_version=saved["version"], **extra)["document"]


def test_every_kind_is_listed_before_anything_is_written() -> None:
    owner = company("dokumenty-lista")

    with tenant(owner):
        listed = list_documents()

    assert [row["kind"] for row in listed["documents"]] == [
        "booking_terms",
        "shop_terms",
        "privacy_policy",
        "cancellation_policy",
    ]
    assert all(
        (row["version"], row["draft"], row["in_force"], row["public_url"]) == (0, None, None, None)
        for row in listed["documents"]
    )
    assert listed["options"]["locales"] == ["pl", "en"]
    assert listed["options"]["default_locale"] == "pl"


def test_a_draft_binds_nobody_and_is_locked_by_version() -> None:
    owner = company("dokumenty-szkic")

    with tenant(owner):
        saved = save_draft(PRIVACY, text=f"  {TEXT}\r\n", locale="pl", expected_version=0)
        assert saved["draft"] == {"text": TEXT, "locale": "pl", "origin_ref": ""}
        assert (saved["version"], saved["in_force"]) == (1, None)
        # Customers get nothing from a draft.
        assert current_document(PRIVACY, "pl") is None
        with pytest.raises(DocumentVersionConflict):
            save_draft(PRIVACY, text="Inny", locale="pl", expected_version=0)
        # The same text again changes nothing, not even the version.
        assert save_draft(PRIVACY, text=TEXT, locale="pl", expected_version=1)["version"] == 1
        with pytest.raises(ValidationError) as refused:
            save_draft(PRIVACY, text=TEXT, locale="de", expected_version=1)
        cleared = save_draft(PRIVACY, text="", locale="pl", expected_version=1)
        with pytest.raises(NotFound):
            read_document("nieznany")

    assert refused.value.detail["locale"][0].code == "locale_not_enabled"
    assert (cleared["draft"], cleared["version"]) == (None, 2)


def test_only_who_manages_customers_documents_writes_them() -> None:
    owner = company("dokumenty-uprawnienia")
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
        assert len(list_documents()["documents"]) == 4
        with pytest.raises(OrganizationPermissionDenied):
            save_draft(PRIVACY, text=TEXT, locale="pl", expected_version=0)

    Role.objects.filter(pk=role.pk).update(permissions=[])
    nobody = Membership.objects.select_related("role", "organization", "user").get(pk=owner.pk)
    with tenant(nobody), pytest.raises(OrganizationPermissionDenied):
        list_documents()


def test_approval_takes_a_person_with_a_fresh_second_factor() -> None:
    owner = company("dokumenty-zatwierdzenie")

    with tenant(owner):
        save_draft(PRIVACY, text=TEXT, locale="pl", expected_version=0)
        preview = approve_draft(PRIVACY, expected_version=1, preview=True)
        # The preview said what would happen and wrote nothing.
        assert preview["effect"] == {
            "number": 1,
            "effective_from": owner.organization.local_today(),
            # No earlier version: today is the earliest day.
            "not_before": None,
            "source_locale": "pl",
            "locales_without_text": ["en"],
        }
        assert not DocumentVersion.all_objects.exists()
        with pytest.raises(StepUpMfaSetupRequired):
            approve_draft(PRIVACY, expected_version=1)
        with_second_factor(owner)
        with pytest.raises(StepUpRequired):
            approve_draft(PRIVACY, expected_version=1)

    assistant = acting_context(
        context_from_membership(owner), via="assistant", ref=f"conversation:{uuid7()}"
    )
    with transaction.atomic(), activate_tenant_context(assistant), stepped_up():
        set_local_organization_id(owner.organization_id)
        with pytest.raises(PersonRequired):
            approve_draft(PRIVACY, expected_version=1)

    with tenant(owner), stepped_up():
        with pytest.raises(ValidationError) as past:
            approve_draft(
                PRIVACY,
                expected_version=1,
                effective_from=owner.organization.local_today() - timedelta(days=1),
            )
        done = approve_draft(PRIVACY, expected_version=1)["document"]
        with pytest.raises(DocumentVersionConflict):
            approve_draft(PRIVACY, expected_version=1)
        with pytest.raises(ValidationError) as empty:
            approve_draft(PRIVACY, expected_version=done["version"])

    assert past.value.detail["effective_from"][0].code == "date_in_past"
    assert empty.value.detail["draft"][0].code == "draft_missing"
    assert (done["draft"], done["version"]) == (None, 2)
    assert done["in_force"]["number"] == 1
    assert done["in_force"]["locales"] == ["pl"]
    assert [row["text"] for row in done["in_force"]["texts"]] == [TEXT]
    assert done["public_url"].endswith(
        f"/documents/{DocumentRoute.objects.get(organization_id=owner.organization_id).public_id}"
    )


def test_the_reader_answers_in_the_language_asked_for_or_not_at_all() -> None:
    owner = with_second_factor(company("dokumenty-czytnik"))
    document = approved(owner)

    with tenant(owner):
        polish = current_document(PRIVACY, "pl")
        # No text in English: nothing, never the Polish one instead.
        assert current_document(PRIVACY, "en") is None
        assert current_document("booking_terms", "pl") is None
    assert polish is not None
    assert (polish.version, polish.locale, polish.text) == (1, "pl", TEXT)
    assert polish.text_hash == document["in_force"]["texts"][0]["text_hash"]
    assert polish.url.endswith(f"/documents/{polish.url.rsplit('/', 1)[1]}")
    assert "/en/" not in polish.url

    with tenant(owner), stepped_up():
        with pytest.raises(ValidationError) as same:
            add_text(
                PRIVACY, number=1, locale="pl", text=TEXT, expected_version=document["version"]
            )
        added = add_text(
            PRIVACY,
            number=1,
            locale="en",
            text="The controller is Studio.",
            expected_version=document["version"],
        )
        corrected = add_text(
            PRIVACY,
            number=1,
            locale="en",
            text="The data controller is Studio.",
            expected_version=added["version"],
        )
        english = current_document(PRIVACY, "en")
        rows = list(DocumentText.all_objects.filter(locale="en").order_by("accepted_at", "id"))

    assert same.value.detail["text"][0].code == "text_unchanged"
    assert corrected["in_force"]["locales"] == ["en", "pl"]
    # The correction is the next row; the first one stays as it was written.
    assert [row.text for row in rows] == [
        "The controller is Studio.",
        "The data controller is Studio.",
    ]
    assert rows[1].provenance["origin"] == "human"
    assert english is not None
    assert (english.text_id, english.text) == (rows[1].id, "The data controller is Studio.")
    assert "/en/documents/" in english.url


def test_a_version_approved_for_later_waits_for_its_day() -> None:
    owner = with_second_factor(company("dokumenty-pozniej"))
    approved(owner)
    later = owner.organization.local_today() + timedelta(days=7)

    document = approved(owner, text="Nowa treść.", effective_from=later)

    with tenant(owner):
        now = current_document(PRIVACY, "pl")
    assert document["in_force"]["number"] == 1
    assert (document["upcoming"]["number"], document["upcoming"]["effective_from"]) == (2, later)
    assert [row["number"] for row in document["versions"]] == [2, 1]
    assert now is not None and now.text == TEXT


def test_no_version_takes_force_before_one_already_approved() -> None:
    owner = with_second_factor(company("dokumenty-kolejnosc"))
    approved(owner)
    today = owner.organization.local_today()
    later = today + timedelta(days=7)
    approved(owner, text="Wersja na później.", effective_from=later)

    # „From today” after a version dated a week ahead would give way to that
    # one when its day came, though it was approved last: refused, with the day.
    with tenant(owner), stepped_up():
        version = read_document(PRIVACY)["document"]["version"]
        saved = save_draft(PRIVACY, text="Poprawka.", locale="pl", expected_version=version)
        with pytest.raises(ValidationError) as refused:
            approve_draft(PRIVACY, expected_version=saved["version"], effective_from=today)
        with pytest.raises(ValidationError) as previewed:
            approve_draft(
                PRIVACY,
                expected_version=saved["version"],
                effective_from=later - timedelta(days=1),
                preview=True,
            )
        # Asked for no day, the earliest possible one is offered: that version's.
        offered = approve_draft(PRIVACY, expected_version=saved["version"], preview=True)
        third = approve_draft(PRIVACY, expected_version=saved["version"], effective_from=later)
        on_the_day = current_document(PRIVACY, "pl")

    for error in (refused, previewed):
        assert [(item["field"], item["code"]) for item in problem_errors(error.value)] == [
            ("effective_from", "before_latest_version")
        ]
    assert later.isoformat() in str(refused.value)
    assert (offered["effect"]["effective_from"], offered["effect"]["not_before"]) == (later, later)
    # The same day is allowed: the one approved last wins it.
    assert third["effect"]["number"] == 3
    assert third["document"]["upcoming"]["number"] == 3
    assert on_the_day is not None and on_the_day.text == TEXT


def test_a_first_version_has_no_day_it_must_wait_for() -> None:
    owner = with_second_factor(company("dokumenty-pierwsza"))
    with tenant(owner), stepped_up():
        saved = save_draft(PRIVACY, text=TEXT, locale="pl", expected_version=0)
        offered = approve_draft(PRIVACY, expected_version=saved["version"], preview=True)
    assert offered["effect"]["effective_from"] == owner.organization.local_today()
    assert offered["effect"]["not_before"] is None


def test_a_translation_typed_by_hand_is_confirmed_after_its_source_was_corrected() -> None:
    owner = with_second_factor(company("dokumenty-potwierdzenie"))
    document = approved(owner)
    english = "The controller of your data is Studio."

    def add(locale: str, text: str) -> dict[str, Any]:
        with tenant(owner), stepped_up():
            return add_text(
                PRIVACY,
                number=1,
                locale=locale,
                text=text,
                expected_version=read_document(PRIVACY)["document"]["version"],
            )

    def stale(read: dict[str, Any]) -> dict[str, bool]:
        return {row["locale"]: row["stale"] for row in read["in_force"]["texts"]}

    first = add("en", english)
    # The same words again say nothing new while the source stands.
    with pytest.raises(ValidationError) as unchanged:
        add("en", english)
    corrected = add("pl", TEXT + "\n\nKontakt: recepcja.")
    confirmed = add("en", english)
    with pytest.raises(ValidationError) as again:
        add("en", english)
    with tenant(owner):
        audit = OrganizationAuditEntry.objects.filter(
            action="customers.document.text_added"
        ).latest("occurred_at")

    assert document["in_force"]["number"] == 1
    assert stale(first) == {"en": False, "pl": False}
    assert [item["code"] for item in problem_errors(unchanged.value)] == ["text_unchanged"]
    # The source was corrected: the translation was read against the old one.
    assert stale(corrected) == {"en": True, "pl": False}
    # Confirmed: the same words, a new row, read against the source as it is.
    assert stale(confirmed) == {"en": False, "pl": False}
    assert (
        next(row["text"] for row in confirmed["in_force"]["texts"] if row["locale"] == "en")
        == english
    )
    assert [item["code"] for item in problem_errors(again.value)] == ["text_unchanged"]
    assert (audit.metadata["locale"], audit.metadata["confirms"]) == ("en", True)


def test_versions_texts_and_consents_are_append_only_in_the_database() -> None:
    owner = with_second_factor(company("dokumenty-dopisywanie"))
    approved(owner)
    with tenant(owner):
        row = current_document(PRIVACY, "pl")
        assert row is not None
        record_consent(source="booking.appointment", source_reference="a-1", text_id=row.text_id)

    for table in (
        "customers_documentversion",
        "customers_documenttext",
        "customers_consentrecord",
    ):
        for statement in (
            f"UPDATE {table} SET organization_id = organization_id",
            f"DELETE FROM {table}",
        ):
            with (
                pytest.raises(DatabaseError, match="append-only"),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(statement)


def test_the_journal_says_who_saw_which_text_and_where() -> None:
    owner = with_second_factor(company("dokumenty-zgody"))
    other = with_second_factor(company("dokumenty-zgody-inna"))
    approved(owner)
    approved(other)
    with tenant(other):
        foreign = current_document(PRIVACY, "pl")
    assert foreign is not None

    with tenant(owner):
        shown = current_document(PRIVACY, "pl")
        assert shown is not None
        person = Customer.all_objects.create(
            organization_id=owner.organization_id,
            display_name="Ewa",
            email="ewa@example.test",
            contact_hash="e" * 64,
        )
        booked = record_consent(
            customer=person,
            text_id=shown.text_id,
            source="booking.appointment",
            source_reference="visit-1",
        )
        # Somebody who is not a customer: the enquiry's id is the subject.
        asked = record_consent(
            text_id=shown.text_id, source="sites.inquiry", source_reference="inquiry-7"
        )
        marketing = record_consent(
            customer=person,
            kind="marketing",
            wording="Chcę dostawać oferty e-mailem.",
            locale="pl",
            source="booking.appointment",
            source_reference="visit-1",
        )
        withdrawn = record_consent(
            customer=person,
            kind="marketing",
            granted=False,
            source="booking.self_service",
            source_reference="visit-1",
        )
        # Another company's text is not this company's to point at.
        with pytest.raises(ValidationError) as unknown:
            record_consent(
                text_id=foreign.text_id, source="booking.appointment", source_reference="x"
            )
        with pytest.raises(ValidationError):
            record_consent(source="booking.appointment", source_reference="x")
        journal = list(ConsentRecord.all_objects.order_by("created_at", "id"))

    assert unknown.value.detail["text_id"][0].code == "text_unknown"
    assert [(row.kind, row.granted, row.source) for row in journal] == [
        ("document", True, "booking.appointment"),
        ("document", True, "sites.inquiry"),
        ("marketing", True, "booking.appointment"),
        ("marketing", False, "booking.self_service"),
    ]
    assert (booked.customer_id, booked.text_hash, booked.locale) == (
        person.id,
        shown.text_hash,
        "pl",
    )
    assert (asked.customer_id, asked.source_reference) == (None, "inquiry-7")
    assert (marketing.document_text_id, len(marketing.text_hash)) == (None, 64)
    assert marketing.wording == "Chcę dostawać oferty e-mailem."
    assert (withdrawn.text_hash, withdrawn.wording, booked.wording) == ("", "", "")


def test_the_database_refuses_a_consent_to_another_companys_text() -> None:
    owner = with_second_factor(company("dokumenty-straznik"))
    other = with_second_factor(company("dokumenty-straznik-inna"))
    approved(other)
    with tenant(other):
        foreign = current_document(PRIVACY, "pl")
    assert foreign is not None

    with pytest.raises(DatabaseError, match="another organization"), tenant(owner):
        ConsentRecord.all_objects.create(
            organization_id=owner.organization_id,
            kind="document",
            document_text_id=foreign.text_id,
            source="booking.appointment",
            source_reference="x",
        )


def test_anybody_reads_the_version_in_force_at_the_public_address() -> None:
    owner = with_second_factor(company("dokumenty-publiczny"))
    approved(owner)
    public_id = DocumentRoute.objects.get(organization_id=owner.organization_id).public_id
    client = APIClient()

    statements: list[str] = []

    def record(execute: Any, sql: str, params: Any, many: bool, context: Any) -> Any:
        statements.append(sql)
        return execute(sql, params, many, context)

    # Not `CaptureQueriesContext`: a request resets the connection's query log.
    with connection.execute_wrapper(record):
        polish = client.get(f"/api/v1/public/documents/{public_id}/", {"locale": "pl"})
    # A reader of another language reads the version's own: nothing is being
    # agreed to on this page.
    german = client.get(f"/api/v1/public/documents/{public_id}/", {"locale": "de"})
    missing = client.get("/api/v1/public/documents/nie-ma-takiego/")

    assert (polish.status_code, german.status_code, missing.status_code) == (200, 200, 404)
    assert polish.json() == {
        "kind": PRIVACY,
        "organization_name": owner.organization.name,
        "version": 1,
        "effective_from": owner.organization.local_today().isoformat(),
        "locale": "pl",
        "locales": ["pl"],
        "text": TEXT,
        "text_hash": polish.json()["text_hash"],
    }
    assert german.json()["locale"] == "pl"
    # The route names the tenant; the tenant is set before the document is read.
    route = next(i for i, sql in enumerate(statements) if "customers_documentroute" in sql)
    tenant_set = next(i for i, sql in enumerate(statements) if "app.organization_id" in sql)
    first_read = next(i for i, sql in enumerate(statements) if "customers_customerdocument" in sql)
    assert route < tenant_set < first_read


def test_a_public_context_reads_only_its_own_company() -> None:
    owner = with_second_factor(company("dokumenty-izolacja"))
    other = company("dokumenty-izolacja-inna")
    approved(owner)

    with public_documents_context(other.organization_id):
        assert current_document(PRIVACY, "pl") is None
    with public_documents_context(owner.organization_id):
        assert current_document(PRIVACY, "pl") is not None


def test_the_panel_reads_and_writes_over_the_api() -> None:
    client, _organization, _user = sites_client(slug="dokumenty-api", role_key="owner")
    url = f"/api/v1/customers/documents/{PRIVACY}/"

    def send(method: str, path: str, body: dict[str, Any]) -> Any:
        csrf = client.get("/api/v1/auth/csrf/").data["csrf_token"]
        return getattr(client, method)(path, body, format="json", HTTP_X_CSRFTOKEN=csrf)

    listed = client.get("/api/v1/customers/documents/")
    saved = send("put", f"{url}draft/", {"text": TEXT, "locale": "pl", "expected_version": 0})
    read = client.get(url)
    preview = send("post", f"{url}approve/preview/", {"expected_version": 1})
    refused = send("post", f"{url}approve/", {"expected_version": 1})
    stale = send("put", f"{url}draft/", {"text": "Inny", "locale": "pl", "expected_version": 0})
    unknown = send("put", f"{url}draft/", {"text": TEXT, "locale": "xx", "expected_version": 1})

    assert (listed.status_code, saved.status_code, read.status_code) == (200, 200, 200)
    assert len(listed.json()["documents"]) == 4
    assert saved.json()["draft"]["text"] == TEXT
    assert read.json()["document"]["version"] == 1
    assert read.json()["options"]["text_max"] == 100_000
    assert (preview.status_code, preview.json()["effect"]["number"]) == (200, 1)
    # An account without two-factor sign-in is told to turn it on, not asked
    # for a code.
    assert (refused.status_code, refused.json()["code"]) == (403, "step_up_mfa_setup_required")
    assert (stale.status_code, stale.json()["code"]) == (409, "customers_document_version_conflict")
    assert unknown.status_code == 400
    assert unknown.json()["errors"][0]["field"] == "locale"


def test_erasing_the_company_takes_its_documents_and_their_route() -> None:
    owner = with_second_factor(company("dokumenty-usuniecie"))
    approved(owner)
    with tenant(owner):
        row = current_document(PRIVACY, "pl")
        assert row is not None
        record_consent(source="sites.inquiry", source_reference="i-1", text_id=row.text_id)
    organization_id = owner.organization_id

    erase_organization(organization=owner.organization, requested_by=None, reason="test")

    assert not DocumentRoute.objects.filter(organization_id=organization_id).exists()
    for model in (CustomerDocument, DocumentVersion, DocumentText, ConsentRecord):
        assert not model.all_objects.filter(organization_id=organization_id).exists()
