"""What is particular to the commands for the company's documents (phase 4d;
ADR-073 §9): the assistant reads them without anybody's name, writes a draft
marked with the conversation that wrote it, and has no way to approve one."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from saas_core.modules.core.organizations import command_executor
from saas_core.modules.core.organizations.command_executor import execute_plan, preview_plan
from saas_core.modules.core.organizations.command_registry import registered_commands
from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    context_from_membership,
)
from saas_core.modules.shared.customers.documents import DOCUMENT_TEXT_MAX, read_document
from saas_core.modules.shared.customers.models import CustomerDocument, DocumentVersion
from test_booking import tenant
from test_command_evals import assistant, clicked, invocation, owner, writes
from test_customers_documents import approved, company, with_second_factor

pytestmark = pytest.mark.django_db

READ = "customers.documents.read@1"
SAVE = "customers.document.draft.save@1"
TERMS = "booking_terms"
PRIVACY = "privacy_policy"


@pytest.fixture(autouse=True)
def features_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(command_executor, "_gates", {"features": lambda *_: None})
    yield


def run(person: Any, acting: Any, key: str, arguments: dict[str, Any]) -> Any:
    plan = [invocation(key, arguments)]
    tokens = clicked(person, acting, plan) if key == SAVE else None
    with activate_tenant_context(acting):
        (result,) = execute_plan(plan, tokens) if tokens else execute_plan(plan)
    return result


def test_the_assistant_reads_the_documents_without_anybodys_name() -> None:
    member = with_second_factor(company("polecenia-odczyt"))
    approved(member, "Administratorem danych jest Studio.")
    person = context_from_membership(member)
    acting = assistant(person)
    with CaptureQueriesContext(connection) as queries:
        listed = run(person, acting, READ, {"kind": None})
        one = run(person, acting, READ, {"kind": PRIVACY})

    assert listed.status == "done", listed
    assert [row["kind"] for row in listed.output["documents"]] == [
        "booking_terms",
        "shop_terms",
        "privacy_policy",
        "cancellation_policy",
    ]
    privacy = listed.output["documents"][2]
    # Every document: what is in force and in which languages, without texts.
    assert (privacy["in_force"]["number"], privacy["in_force"]["locales"]) == (1, ["pl"])
    assert "texts" not in privacy["in_force"]
    assert listed.output["locales"] == ["pl", "en"]
    assert listed.output["text_max"] == DOCUMENT_TEXT_MAX
    # One document: the text customers read, and nobody's name beside it.
    (document,) = one.output["documents"]
    assert document["in_force"]["texts"] == [
        {"locale": "pl", "text": "Administratorem danych jest Studio."}
    ]
    assert member.user.email not in str(one.output) and "approved_by" not in str(one.output)
    assert writes(queries) == []


def test_a_draft_from_the_assistant_names_its_conversation_and_binds_nobody() -> None:
    member = with_second_factor(company("polecenia-szkic"))
    approved(member, "Wizytę można odwołać dzień wcześniej.", TERMS)
    person = context_from_membership(member)
    acting = assistant(person)
    text = "Wizytę można odwołać dzień wcześniej.\n\nSpóźnienie skraca wizytę."
    plan = [invocation(SAVE, {"kind": TERMS, "text": text, "locale": "pl"})]
    with activate_tenant_context(acting):
        (group,) = preview_plan(plan).groups
    (effect,) = group.calls[0].preview.effects
    # A reversible change of a working copy: one click, no second factor.
    assert (group.risk, group.calls[0].step_up_required, effect.kind) == ("draft", False, "created")
    assert "nikogo nie wiąże" in effect.summary["pl"]
    assert "Klienci dalej czytają wersję 1" in effect.summary["pl"]

    tokens = clicked(person, acting, plan)
    with activate_tenant_context(acting):
        (result,) = execute_plan(plan, tokens)
    assert result.status == "done", result
    (document,) = result.output["documents"]
    assert document["draft"] == {"text": text, "locale": "pl", "origin_ref": acting.acting_ref}
    # Customers keep the version in force; the draft made no version.
    assert document["in_force"]["number"] == 1
    assert DocumentVersion.all_objects.filter(organization_id=person.organization_id).count() == 1
    with tenant(member):
        assert read_document(TERMS)["document"]["draft"]["origin_ref"] == acting.acting_ref

    # The same text again changes nothing, and the consent says nothing will.
    with activate_tenant_context(acting):
        (group,) = preview_plan(plan).groups
    assert group.calls[0].preview.effects == ()

    # An empty text removes the draft, and says so before the click.
    cleared = [invocation(SAVE, {"kind": TERMS, "text": "", "locale": "pl"})]
    with activate_tenant_context(acting):
        (group,) = preview_plan(cleared).groups
    assert group.calls[0].preview.effects[0].kind == "deleted"
    tokens = clicked(person, acting, cleared)
    with activate_tenant_context(acting):
        (result,) = execute_plan(cleared, tokens)
    assert result.output["documents"][0]["draft"] is None


def test_a_draft_the_service_would_refuse_is_refused_before_the_click() -> None:
    person = owner("polecenia-odmowa", SAVE)
    before = list(CustomerDocument.all_objects.values_list("draft_text", "version"))
    with activate_tenant_context(assistant(person)):
        (too_long,) = preview_plan([
            invocation(
                SAVE, {"kind": PRIVACY, "text": "a" * (DOCUMENT_TEXT_MAX + 1), "locale": "pl"}
            )
        ]).refusals
        (unknown,) = preview_plan([
            invocation(SAVE, {"kind": "regulamin", "text": "Treść.", "locale": "pl"})
        ]).refusals
    assert [(error["field"], error["code"]) for error in too_long.errors] == [
        ("text", "max_length")
    ]
    assert "kind" in [error["field"] for error in unknown.errors]
    assert list(CustomerDocument.all_objects.values_list("draft_text", "version")) == before


def test_no_command_approves_a_document() -> None:
    """Approval is a person's, with a fresh second factor, in the panel."""
    assert sorted(
        spec.key for spec in registered_commands() if spec.module == "shared.customers"
    ) == [SAVE, READ]
