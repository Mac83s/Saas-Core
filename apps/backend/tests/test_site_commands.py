"""What is particular to the site commands (A1b-11): the assistant's text is
marked as AI text and stays a draft; a legal page is never written by it; a
page drafted from a template is not published."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from command_evals.sites import _english, _memory_storage, _page, _template_draft
from saas_core.modules.core.organizations import command_executor
from saas_core.modules.core.organizations.command_executor import execute_plan, preview_plan
from saas_core.modules.core.organizations.context import activate_tenant_context
from saas_core.modules.shared.sites.models import Page, PageLocaleVersion, PageType
from test_command_evals import assistant, clicked, invocation, owner

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def features_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(command_executor, "_gates", {"features": lambda *_: None})
    yield


def test_the_assistant_s_text_is_ai_text_in_a_draft_named_after_its_conversation() -> None:
    person = owner("ai-text", "sites.locale_body.save@1")
    acting = assistant(person)
    plan = [invocation("sites.locale_body.save@1", _english(person, "Welcome to the lake"))]
    tokens = clicked(person, acting, plan)
    with activate_tenant_context(acting):
        (result,) = execute_plan(plan, tokens)

    assert result.status == "done", result
    assert result.output["published"] is False
    version = PageLocaleVersion.all_objects.filter(organization_id=person.organization_id).latest(
        "number"
    )
    assert version.origin_ref == acting.acting_ref
    assert {
        unit["provenance"]["origin"] for unit in version.units.values() if "provenance" in unit
    } >= {"ai"}


def test_a_legal_page_is_never_written_by_the_assistant() -> None:
    person = owner("legal-text", "sites.locale_body.save@1")
    Page.all_objects.filter(pk=_page(person).id).update(page_type=PageType.LEGAL)
    with activate_tenant_context(assistant(person)):
        (refusal,) = preview_plan([
            invocation("sites.locale_body.save@1", _english(person, "Terms"))
        ]).refusals

    assert refusal.code == "person_required"


def test_a_page_drafted_from_a_template_is_not_published() -> None:
    person = owner("template-draft", "sites.page_draft.from_template@1")
    acting = assistant(person)
    plan = [invocation("sites.page_draft.from_template@1", _template_draft(person))]
    tokens = clicked(person, acting, plan)
    with _memory_storage(), activate_tenant_context(acting):
        (result,) = execute_plan(plan, tokens)

    assert result.status == "done", result
    page = Page.all_objects.get(pk=result.output["page_id"])
    assert (page.key, page.current_draft_id is not None) == ("oferta", True)
    assert result.output["published"] is False
