"""A membership acting for its person (ADR-076 §6) meets the operations ADR-035
§4 and ADR-044 keep for a person as a refusal, until a consent gate or ADR-069
opens one: acting for a person is not the person deciding. The same person,
acting directly, passes as before."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import uuid7

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.context import (
    ACTING_PERSON_GATE_ALLOWED,
    TenantContext,
    acting_context,
    activate_tenant_context,
    context_from_membership,
)
from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.shared.sites.connections import ProposalNotFound, accept_proposal
from saas_core.modules.shared.sites.domain_services import (
    change_platform_domain,
    create_custom_domain,
)
from saas_core.modules.shared.sites.models import PageType
from saas_core.modules.shared.sites.services import (
    PersonRequired,
    assert_person_required,
    publish_site,
    save_draft,
    set_page_type,
)
from test_sites_api import (
    create_page,
    create_site,
    csrf_value,
    save_translation,
    sites_client,
)
from test_sites_api import save_draft as save_draft_request

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    # Every test signs the owner in; five sign-ins a minute is the login limit.
    cache.clear()


TEXT = {"block_type": "core.rich_text", "schema_version": 1, "data": {"text": "Nowa treść."}}


def person_and_assistant(slug: str) -> tuple[APIClient, TenantContext, TenantContext]:
    """The owner signed in, and the same membership acting through the
    assistant in one of the owner's conversations."""
    client, organization, user = sites_client(slug=slug, role_key="owner")
    membership = Membership.objects.select_related("role").get(organization=organization, user=user)
    person = context_from_membership(membership)
    return (
        client,
        person,
        acting_context(person, via="assistant", ref=f"conversation:{uuid7()}"),
    )


def draft(page_id: Any, blocks: list[dict[str, Any]], key: str) -> Any:
    return save_draft(
        page_id=page_id,
        expected_version=0,
        blocks=blocks,
        media_asset_ids=[],
        idempotency_key=key,
    )


def test_the_whole_site_is_published_by_the_person_not_the_assistant() -> None:
    client, person, assistant = person_and_assistant("acting-publish")
    site = create_site(client)
    page = create_page(client, site.data["id"])
    save_draft_request(
        client, page.data["id"], expected_version=0, idempotency_key="ap-draft", heading="Start"
    )
    save_translation(
        client,
        page.data["id"],
        "pl",
        expected_version=0,
        slug="start",
        title="Start",
        description="Strona startowa",
        idempotency_key="ap-translation",
    )

    with activate_tenant_context(assistant), pytest.raises(PersonRequired):
        publish_site(site_id=site.data["id"], idempotency_key="ap-assistant")
    with activate_tenant_context(person):
        assert publish_site(site_id=site.data["id"], idempotency_key="ap-person").created


def test_a_domain_is_changed_by_the_person_not_the_assistant() -> None:
    client, person, assistant = person_and_assistant("acting-domain")
    site = create_site(client)

    with activate_tenant_context(assistant):
        with pytest.raises(PersonRequired):
            change_platform_domain(
                site_id=site.data["id"], label="nowa-nazwa", idempotency_key="ad-assistant"
            )
        with pytest.raises(PersonRequired):
            create_custom_domain(
                site_id=site.data["id"],
                hostname="www.acting-domain.test",
                idempotency_key="ad-assistant-custom",
            )
    with activate_tenant_context(person):
        changed = change_platform_domain(
            site_id=site.data["id"], label="nowa-nazwa", idempotency_key="ad-person"
        )
    assert changed.created
    assert changed.value.hostname.startswith("nowa-nazwa.")


def test_a_content_proposal_is_accepted_by_the_person_not_the_assistant() -> None:
    """ADR-044: accepting what an automation proposed is a person's review."""
    _, person, assistant = person_and_assistant("acting-proposal")
    proposal_id = uuid7()

    with activate_tenant_context(assistant), pytest.raises(PersonRequired):
        accept_proposal(proposal_id=proposal_id, review_token="token")
    # The person is past the gate: what answers is the proposal that is not there.
    with activate_tenant_context(person), pytest.raises(ProposalNotFound):
        accept_proposal(proposal_id=proposal_id, review_token="token")


def test_a_legal_page_is_written_by_the_person_and_an_ordinary_one_by_either() -> None:
    client, person, assistant = person_and_assistant("acting-legal")
    site = create_site(client)
    legal = create_page(client, site.data["id"], key="regulamin", idempotency_key="al-legal")
    typed = client.put(
        f"/api/v1/sites/pages/{legal.data['id']}/type/",
        {"page_type": PageType.LEGAL},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert typed.status_code == 200, typed.data
    about = create_page(client, site.data["id"], key="o-nas", idempotency_key="al-about")

    with activate_tenant_context(assistant):
        with pytest.raises(PersonRequired):
            draft(legal.data["id"], [TEXT], "al-assistant-legal")
        assert draft(about.data["id"], [TEXT], "al-assistant-about").created
    with activate_tenant_context(person):
        assert draft(legal.data["id"], [TEXT], "al-person-legal").created


def test_a_page_is_typed_legal_or_untyped_by_the_person_not_the_assistant() -> None:
    client, person, assistant = person_and_assistant("acting-type")
    site = create_site(client)
    legal = create_page(client, site.data["id"], key="regulamin", idempotency_key="at-legal")
    about = create_page(client, site.data["id"], key="o-nas", idempotency_key="at-about")
    with activate_tenant_context(person):
        set_page_type(page_id=legal.data["id"], page_type=PageType.LEGAL)

    with activate_tenant_context(assistant):
        with pytest.raises(PersonRequired):
            set_page_type(page_id=legal.data["id"], page_type=PageType.LANDING)
        with pytest.raises(PersonRequired):
            set_page_type(page_id=about.data["id"], page_type=PageType.LEGAL)
        assert set_page_type(page_id=about.data["id"], page_type=PageType.SERVICE).page_type == (
            PageType.SERVICE
        )
    with activate_tenant_context(person):
        assert set_page_type(page_id=legal.data["id"], page_type=PageType.LANDING).page_type == (
            PageType.LANDING
        )


def test_prices_and_new_quotes_are_a_persons_words_not_the_assistants() -> None:
    client, person, assistant = person_and_assistant("acting-blocks")
    site = create_site(client)
    page = create_page(client, site.data["id"])
    pricing = {
        "block_type": "core.pricing",
        "schema_version": 1,
        "data": {"title": "Cennik", "items": [{"name": "Usługa", "price": "100 zł"}]},
    }
    quote = {
        "block_type": "core.quote",
        "schema_version": 1,
        "data": {"quote": "Słowa właściciela.", "author": "Anna"},
    }

    with activate_tenant_context(assistant):
        with pytest.raises(PersonRequired, match="Cennik"):
            draft(page.data["id"], [TEXT, pricing], "ab-assistant-pricing")
        with pytest.raises(PersonRequired, match="Cytaty"):
            draft(page.data["id"], [TEXT, quote], "ab-assistant-quote")
    with activate_tenant_context(person):
        assert draft(page.data["id"], [TEXT, pricing, quote], "ab-person").created


def test_a_label_opens_for_one_consented_run_within_its_channels_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing is open before a label is in the ceiling. Even then the label
    opens only for a run a consent covers (`acting_opened`), per channel and
    per label, and never for an integration (ADR-076 §6)."""
    person = TenantContext(
        organization_id=uuid7(),
        membership_id=uuid7(),
        actor_id=uuid7(),
        role_key="owner",
        permissions=frozenset(),
    )
    assistant = acting_context(person, via="assistant", ref=f"conversation:{uuid7()}")
    translation = acting_context(person, via="ai_translation", ref=f"translation_job:{uuid7()}")
    # The labels open today, each after a click: removing a company language
    # (TL10a), deciding on an AI translation and consenting to its automation
    # (TL6c). The translation channel reaches none (ADR-069 pkt 15).
    assert {
        "assistant": frozenset({
            "Usunięcie języka firmy",
            "Decyzja o tłumaczeniu AI",
            "Zgoda na automat tłumaczeń",
        })
    } == ACTING_PERSON_GATE_ALLOWED
    assert "Cennik" not in ACTING_PERSON_GATE_ALLOWED["assistant"]
    with pytest.raises(ValueError, match="acting_opened"):
        replace(translation, acting_opened=frozenset({"Cennik"}))

    monkeypatch.setitem(ACTING_PERSON_GATE_ALLOWED, "ai_translation", frozenset({"Cennik"}))
    consented = replace(translation, acting_opened=frozenset({"Cennik"}))

    assert_person_required(consented, "Cennik")
    assert_person_required(person, "Strona prawna")
    for context, what in (
        (translation, "Cennik"),
        (consented, "Strona prawna"),
        (assistant, "Cennik"),
        (replace(person, principal_kind="api_key"), "Cennik"),
    ):
        with pytest.raises(PersonRequired):
            assert_person_required(context, what)
    with pytest.raises(ValueError, match="acting_opened"):
        replace(assistant, acting_opened=frozenset({"Cennik"}))
    with pytest.raises(ValueError):
        replace(person, acting_opened=frozenset({"Cennik"}))
