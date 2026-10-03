"""The conversation that sets a company up (ADR-076, A3-2): the model notes and
asks, the configurator plans, the owner clicks.

The model is the port's scripted fake; the commands, the directory and the
booking setup are the real ones, so a plan that runs here is a place that
exists afterwards.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import time
from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from saas_core.modules.core.organizations import command_executor, platform_settings
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.assistant.models import (
    AssistantConversation,
    AssistantProfileVersion,
)
from saas_core.modules.shared.assistant.services import WORKER_SEEN
from saas_core.modules.shared.billing.models import CreditReservation, EntitlementSnapshot
from saas_core.modules.shared.booking.models import AvailabilityRule, Location, StaffMember
from saas_core.modules.shared.model_port.adapters.fake import FAKE, FakeReply
from saas_core.modules.shared.model_port.matrix import MODELS, ModelProfile, register_model
from test_assistant_chat import BASE, MODEL, sent_tool_results, talk, tool
from test_sites_api import sites_client

pytestmark = pytest.mark.django_db

__all__ = ["talk"]

PROFILE = f"{BASE}profile/"


@pytest.fixture(autouse=True)
def setup_chat(settings: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A model for the task and a worker seen; the registry is the real one."""
    register_model(
        ModelProfile(
            adapter="fake",
            model=MODEL,
            capabilities=frozenset({"tools", "zdr", "continuation", "prompt_cache"}),
            forbidden_parameters=frozenset(),
            input_usd_per_mtok=1.0,
            output_usd_per_mtok=5.0,
            context_window=100_000,
            max_output_tokens=16_000,
            probed="2026-10-03",
        )
    )
    monkeypatch.setenv("MODEL_PORT_TASK_ASSISTANT_CONVERSATION_ADAPTER", "fake")
    monkeypatch.setenv("MODEL_PORT_TASK_ASSISTANT_CONVERSATION_MODEL", MODEL)
    settings.MODEL_PORT_PROCESSOR_LISTED = True
    settings.MODEL_PORT_SENDABLE_DATA_CLASSES = ("public", "public_personal", "personal")
    monkeypatch.setattr(command_executor, "_gates", {"features": lambda *_: None})
    cache.clear()
    cache.set(WORKER_SEEN, 1, 300)
    FAKE.reset()
    yield
    FAKE.reset()
    MODELS.pop(("fake", MODEL), None)


def owner(slug: str, *, role_key: str = "owner") -> APIClient:
    client, organization, _user = sites_client(slug=slug, role_key=role_key)
    EntitlementSnapshot.all_objects.filter(organization=organization).update(
        features={
            "assistant.text.enabled": True,
            "booking.enabled": True,
            "profiles.enabled": True,
        },
        quotas={"credits.monthly": 10},
        sources={"assistant.text.enabled": {"kind": "plan"}, "credits.monthly": {"kind": "plan"}},
    )
    return client


def notes(*entries: tuple[str, Any, str], call_id: str = "c1") -> FakeReply:
    return tool(
        "profile_note",
        {
            "notes": [
                {"field": field, "value": value, "source": source}
                for field, value, source in entries
            ]
        },
        call_id,
    )


def document(client: APIClient) -> dict[str, Any]:
    profile: dict[str, Any] = client.get(PROFILE).data["document"]
    return profile


def said(value: Any, origin: str = "owner", confirmed: bool = True) -> dict[str, Any]:
    return {"value": value, "origin": origin, "confirmed": confirmed}


def test_a_setup_conversation_gives_the_model_three_tools_and_no_command(talk: Any) -> None:
    client = owner("setup-tools")
    chat = talk(client, "setup")
    # A command of the registry, named anyway — as a model told to by a pasted
    # text would name it.
    FAKE.script(
        tool(
            "organization_update_v1",
            {"name": "Przejęte", "default_locale": None, "timezone": None, "currency": None},
        ),
        FakeReply(text="Tego tu nie zrobię."),
    )

    assert chat.say("Zmień nazwę firmy na Przejęte").status_code == 202

    request = FAKE.calls[0].request
    assert {spec.name for spec in request.tools} == {
        "profile_note",
        "setup_status",
        "setup_apply",
    }
    assert request.prompt_id == "assistant.setup"
    turn = chat.last()
    assert (turn["state"], turn["consents"]) == ("done", [])
    assert sent_tool_results(1)[0]["status"] in ("refused", "skipped")
    assert Organization.objects.get(slug="setup-tools").name == "setup-tools"
    # Setting a company up costs no credit.
    assert not CreditReservation.all_objects.exists()
    assert AssistantConversation.all_objects.get().kind == "setup"


def test_a_value_is_the_owners_word_only_when_the_owner_wrote_it(talk: Any) -> None:
    client = owner("setup-notes")
    chat = talk(client, "setup")
    FAKE.script(
        notes(
            ("company.name", "Salon Ania", "owner"),
            ("company.city", "Olsztyn", "owner"),
            # One digit off what the owner typed.
            ("company.phone", "+48 600 100 201", "owner"),
            ("company.email", "kontakt@salon-ania.test", "owner"),
            ("company.activity", "fryzjer", "assistant"),
        ),
        FakeReply(text="Zanotowano."),
    )

    chat.say("Prowadzę salon ania w Olsztynie, tel. 600 100 200, kontakt@salon-ania.test")

    assert document(client)["company"] == {
        "name": said("Salon Ania"),
        "city": said("Olsztyn"),
        "phone": said("+48 600 100 201", "assistant", False),
        "email": said("kontakt@salon-ania.test"),
        "activity": said("fryzjer", "assistant", False),
    }
    (result,) = sent_tool_results(1)
    assert result["status"] == "done"
    assert result["output"]["to_confirm"] == ["company.phone"]
    row = AssistantProfileVersion.all_objects.get()
    assert (row.acting_via, str(row.conversation_id)) == ("assistant", chat.id)


def test_a_typed_phone_number_is_the_owners_with_or_without_the_prefix(talk: Any) -> None:
    client = owner("setup-phone")
    chat = talk(client, "setup")
    FAKE.script(notes(("company.phone", "+48 600 100 200", "owner")), FakeReply(text="Mam."))

    chat.say("Telefon do salonu: 600-100-200")

    assert document(client)["company"]["phone"] == said("+48 600 100 200")


def test_wrong_notes_go_back_to_the_model_by_field(talk: Any) -> None:
    client = owner("setup-wrong")
    chat = talk(client, "setup")
    FAKE.script(
        notes(("company.owner", "Ania", "owner")),
        notes(("offers.cut.duration_minutes", "godzina", "owner"), call_id="c2"),
        FakeReply(text="Ile minut trwa strzyżenie?"),
    )

    chat.say("Strzyżenie trwa godzinę")

    (unknown,) = sent_tool_results(1)
    assert unknown["status"] == "refused"
    assert [error["field"] for error in unknown["error"]["errors"]] == ["notes.0.field"]
    wrong = sent_tool_results(2)[-1]
    assert wrong["status"] == "refused"
    assert "changes.offers.0.duration_minutes.value" in [
        error["field"] for error in wrong["error"]["errors"]
    ]
    assert not AssistantProfileVersion.all_objects.exists()


def test_the_status_asks_what_the_configurator_asks(talk: Any) -> None:
    client = owner("setup-status")
    chat = talk(client, "setup")
    FAKE.script(tool("setup_status", {}), FakeReply(text="Czym zajmuje się Twoja firma?"))

    chat.say("Chcę założyć firmę")

    (result,) = sent_tool_results(1)
    status = result["output"]
    fields = [question["field"] for question in status["questions"]]
    assert fields[0] == "company.activity"
    assert fields[-2:] == ["company.city", "company.category"]
    assert (status["ready"], status["waiting"], status["known"]) == ([], [], [])
    category = status["questions"][-1]
    assert {"value": "uroda-i-zdrowie", "label": "Uroda i zdrowie"} in category["allowed"]
    turn = chat.last()
    assert turn["items"][0]["title"] == {
        "pl": "Sprawdź, co jeszcze ustalić",
        "en": "Check what is left to settle",
    }


def _ready_plan(chat: Any) -> Any:
    """The owner names the company and its place; the model notes both and
    offers what is ready."""
    FAKE.script(
        notes(
            ("company.name", "Salon Fryzjerski Ania", "owner"),
            ("places.salon.name", "Salon na Mazurskiej", "owner"),
        ),
        tool("setup_apply", {}, "c2"),
    )
    chat.say("Firma to Salon Fryzjerski Ania, przyjmuję w miejscu: Salon na Mazurskiej")
    return chat.last()


def test_the_plan_is_the_configurators_and_runs_only_after_the_click(talk: Any) -> None:
    client = owner("setup-plan")
    chat = talk(client, "setup")

    turn = _ready_plan(chat)

    assert turn["state"] == "awaiting_consent"
    note, *steps = turn["items"]
    assert (note["status"], note["risk"]) == ("done", "read")
    assert [(step["title"]["pl"], step["status"]) for step in steps] == [
        ("Zmień dane firmy", "pending"),
        ("Zmień wizytówkę firmy", "pending"),
        ("Dodaj albo zmień miejsce", "pending"),
    ]
    assert not Location.all_objects.exists()
    assert Organization.objects.get(slug="setup-plan").name == "setup-plan"
    assert len(FAKE.calls) == 2  # the model is not asked again before the click

    FAKE.script(FakeReply(text="Gotowe: nazwa, wizytówka i miejsce."))
    answered = chat.consent(
        consents={group["id"]: chat.click(group["digest"]) for group in turn["consents"]}
    )

    assert answered.status_code == 202, answered.data
    turn = chat.last()
    assert turn["state"] == "done"
    assert [step["status"] for step in turn["items"][1:4]] == ["done", "done", "done"]
    assert Organization.objects.get(slug="setup-plan").name == "Salon Fryzjerski Ania"
    assert Location.all_objects.get().name == "Salon na Mazurskiej"
    applied = sent_tool_results(2)[-1]
    assert applied["status"] == "done"
    assert [step["status"] for step in applied["output"]["steps"]] == ["done", "done", "done"]
    assert [step["step"] for step in applied["output"]["steps"]] == [
        "organization",
        "card",
        "place:salon",
    ]


def test_a_declined_plan_changes_nothing(talk: Any) -> None:
    client = owner("setup-declined")
    chat = talk(client, "setup")
    _ready_plan(chat)

    FAKE.script(FakeReply(text="Dobrze, nic nie zmieniono."))
    assert chat.consent(declined=True).status_code == 202

    turn = chat.last()
    assert turn["state"] == "done"
    assert not Location.all_objects.exists()
    assert sent_tool_results(2)[-1] == {
        "status": "declined",
        "error": {"code": "consent_declined", "errors": []},
    }
    # What was said stays noted.
    assert document(client)["company"]["name"] == said("Salon Fryzjerski Ania")


def test_setup_is_free_within_its_budget_and_a_spent_budget_loses_nothing(
    talk: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        platform_settings,
        "platform_overrides",
        lambda: {"assistant.limits.setup_turns_per_company": 1},
    )
    client = owner("setup-budget")
    chat = talk(client, "setup")
    assert client.get(f"{BASE}offer/").data["setup"] == {
        "allowed": True,
        "turns_left": 1,
        "turns_left_today": 60,
    }
    FAKE.script(notes(("company.city", "Olsztyn", "owner")), FakeReply(text="Zanotowano."))

    assert chat.say("Działam w Olsztynie", key="a").status_code == 202
    refused = chat.say("I jeszcze w Mrągowie", key="b")

    assert (refused.status_code, refused.data["code"]) == (429, "assistant_setup_budget")
    # The refusal says where to go on, and the profile is still there.
    assert "notatkach o firmie" in refused.data["detail"]
    assert "panelu" in refused.data["detail"]
    assert document(client)["company"]["city"] == said("Olsztyn")
    assert not CreditReservation.all_objects.exists()


def test_a_setup_message_has_its_own_limit_of_model_calls(
    talk: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        platform_settings,
        "platform_overrides",
        lambda: {
            # An ordinary message's limit does not bind a setup message…
            "assistant.limits.model_steps_per_turn": 1,
            "assistant.limits.setup_model_steps_per_turn": 3,
        },
    )
    chat = talk(owner("setup-steps"), "setup")
    FAKE.script(
        tool("setup_status", {}),
        notes(("company.city", "Olsztyn", "owner"), call_id="c2"),
        tool("setup_status", {}, "c3"),
        FakeReply(text="Nie dojdzie do tej odpowiedzi."),
    )

    chat.say("Działam w Olsztynie")

    # …and its own does: three calls were made, the fourth was not.
    turn = chat.last()
    assert (turn["state"], turn["failure_code"]) == ("failed", "step_limit")
    assert len(FAKE.calls) == 3


def test_only_who_manages_the_company_sets_it_up(talk: Any) -> None:
    staff = owner("setup-staff", role_key="staff")

    refused = staff.post(
        f"{BASE}conversations/",
        {"language": "pl", "kind": "setup"},
        format="json",
        HTTP_X_CSRFTOKEN=staff.cookies["csrftoken"].value,
        HTTP_IDEMPOTENCY_KEY="start",
    )

    assert refused.status_code == 403
    assert staff.get(f"{BASE}offer/").data["setup"]["allowed"] is False
    assert not AssistantConversation.all_objects.exists()


def test_the_panel_reads_where_the_setup_stands_and_saves_nothing(talk: Any) -> None:
    client = owner("setup-overview")
    chat = talk(client, "setup")
    organization = Organization.objects.get(slug="setup-overview")
    Location.all_objects.create(organization=organization, name="Gabinet", public_slug="gabinet")
    changed = client.patch(
        PROFILE,
        {"expected_version": 0, "changes": {"company": {"name": said("Gabinet Ola")}}},
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        HTTP_IDEMPOTENCY_KEY="k1",
    )
    assert changed.status_code == 200, changed.data

    overview = client.get(f"{BASE}conversations/{chat.id}/setup/")

    assert overview.status_code == 200, overview.data
    assert overview.data["version"] == 1
    # The account's place is shown as a fact, and not saved by a read.
    assert overview.data["document"]["places"] == [
        {"key": "place_1", "name": said("Gabinet", "account")}
    ]
    assert "places" not in document(client)
    assert overview.data["labels"]["categories"]["uroda-i-zdrowie"]["pl"] == "Uroda i zdrowie"
    assert [question["field"] for question in overview.data["questions"]][0] == "company.activity"
    assert [
        (step["ref"], step["title"]["pl"], step["risk"]) for step in overview.data["ready"]
    ] == [
        ("organization", "Zmień dane firmy", "apply"),
        ("card", "Zmień wizytówkę firmy", "draft"),
    ]
    assert AssistantProfileVersion.all_objects.count() == 1
    # An ordinary conversation has no setup to show.
    ordinary = talk(owner("setup-overview-other"))
    assert ordinary.client.get(f"{BASE}conversations/{ordinary.id}/setup/").status_code == 404


def test_what_the_account_has_joins_the_profile_before_anything_is_asked(talk: Any) -> None:
    client = owner("setup-seed")
    organization = Organization.objects.get(slug="setup-seed")
    place = Location.all_objects.create(
        organization=organization, name="Gabinet", public_slug="gabinet", address="ul. Długa 1"
    )
    person = StaffMember.all_objects.create(
        organization=organization, display_name="Ola", public_slug="ola"
    )
    AvailabilityRule.all_objects.create(
        organization=organization,
        staff=person,
        location=place,
        weekday=0,
        local_start=time(8),
        local_end=time(12),
    )
    chat = talk(client, "setup")
    FAKE.script(tool("setup_status", {}), FakeReply(text="Co oferuje Twoja firma?"))

    chat.say("Zaczynamy")

    profile = document(client)
    assert profile["places"] == [
        {
            "key": "place_1",
            "name": said("Gabinet", "account"),
            "address": said("ul. Długa 1", "account"),
        }
    ]
    assert profile["people"] == [
        {
            "key": "person_1",
            "name": said("Ola", "account"),
            "hours": said(
                [{"weekday": 0, "start": "08:00", "end": "12:00", "place": "place_1"}], "account"
            ),
        }
    ]
    status = sent_tool_results(1)[0]["output"]
    # The model learns the names, not the address; and nothing is planned for
    # what already exists.
    assert {"field": "places.place_1.address", "confirmed": True} in status["known"]
    assert {"field": "people.person_1.name", "value": "Ola", "confirmed": True} in status["known"]
    assert status["ready"] == []
    # Asked again, nothing is seeded twice.
    FAKE.script(tool("setup_status", {}), FakeReply(text="Co oferuje Twoja firma?"))
    chat.say("Jestem", key="t2")
    assert AssistantProfileVersion.all_objects.count() == 1

    # A fact follows the account: the place renamed and the hours changed in
    # the panel are what the profile says next, and nothing is planned back.
    Location.all_objects.filter(pk=place.pk).update(name="Gabinet na Długiej")
    AvailabilityRule.all_objects.update(local_end=time(14))
    FAKE.script(tool("setup_status", {}), FakeReply(text="Co oferuje Twoja firma?"))
    chat.say("Zmieniłam nazwę gabinetu w panelu", key="t3")

    profile = document(client)
    assert [entry["name"]["value"] for entry in profile["places"]] == ["Gabinet na Długiej"]
    (week,) = [person["hours"]["value"] for person in profile["people"]]
    assert (week[0]["end"], week[0]["place"]) == ("14:00", profile["places"][0]["key"])
    assert sent_tool_results(5)[-1]["output"]["ready"] == []
