"""The company's profile (A2): what the owner said about the company, kept as
versions. A save changes the profile and nothing in the account; a change
names the version it saw; and only who manages the company reads it."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.context import (
    TenantContext,
    acting_context,
    activate_tenant_context,
)
from saas_core.modules.core.organizations.models import Membership, Organization
from saas_core.modules.shared.assistant.models import AssistantProfileVersion
from saas_core.modules.shared.assistant.profile import read_profile, save_profile
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from test_sites_api import csrf_value, sites_client
from test_tenant_context import context_for

pytestmark = pytest.mark.django_db

URL = "/api/v1/assistant/profile/"


@pytest.fixture(autouse=True)
def no_throttle_left_over() -> None:
    cache.clear()


def said(value: Any, origin: str = "owner", confirmed: bool = True) -> dict[str, Any]:
    return {"value": value, "origin": origin, "confirmed": confirmed}


def manager(slug: str, *, role_key: str = "owner", in_plan: bool = True) -> APIClient:
    client, organization, _user = sites_client(slug=slug, role_key=role_key)
    EntitlementSnapshot.all_objects.filter(organization=organization).update(
        features={"assistant.text.enabled": in_plan},
        sources={"assistant.text.enabled": {"kind": "plan"}},
    )
    return client


def change(
    client: APIClient,
    changes: dict[str, Any],
    version: int,
    *,
    key: str = "",
    preview: bool = False,
) -> Any:
    if preview:
        return client.post(
            f"{URL}preview/",
            {"expected_version": version, "changes": changes},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_value(client),
        )
    return client.patch(
        URL,
        {"expected_version": version, "changes": changes},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=key or str(uuid4()),
    )


def test_the_profile_starts_empty_and_a_change_is_its_next_version() -> None:
    client = manager("profile-first")
    empty = client.get(URL)
    assert empty.status_code == 200
    assert empty.data == {
        "schema": "company-profile.v1",
        "version": 0,
        "document": {"schema": "company-profile.v1"},
        "updated_at": None,
    }

    company = {"name": said("Salon Ania"), "city": said("Olsztyn")}
    saved = change(client, {"company": company}, 0)

    assert saved.status_code == 200, saved.data
    assert (saved.data["version"], saved.data["changed"]) == (1, ["company.city", "company.name"])
    assert client.get(URL).data["document"] == {"schema": "company-profile.v1", "company": company}
    row = AssistantProfileVersion.all_objects.get()
    membership = Membership.objects.get(organization__slug="profile-first")
    assert (row.created_by_id, row.membership_id) == (membership.user_id, membership.id)
    assert (row.acting_via, row.conversation_id) == ("", None)


def test_a_change_names_the_version_it_saw() -> None:
    client = manager("profile-version")
    assert change(client, {"company": {"name": said("Salon Ania")}}, 0).status_code == 200

    late = change(client, {"company": {"name": said("Salon Ola")}}, 0)

    assert late.status_code == 409
    assert late.data["code"] == "assistant_profile_version_conflict"
    assert AssistantProfileVersion.all_objects.count() == 1


def test_null_removes_a_field_and_a_list_is_replaced_whole() -> None:
    client = manager("profile-merge")
    offers = [{"key": "cut", "name": said("Strzyżenie")}, {"key": "dye", "name": said("Farba")}]
    first = {"company": {"name": said("Salon Ania"), "city": said("Olsztyn")}, "offers": offers}
    assert change(client, first, 0).status_code == 200

    saved = change(client, {"company": {"city": None}, "offers": offers[:1]}, 1)

    assert saved.status_code == 200, saved.data
    assert saved.data["changed"] == ["company.city", "offers"]
    assert saved.data["document"] == {
        "schema": "company-profile.v1",
        "company": {"name": said("Salon Ania")},
        "offers": offers[:1],
    }
    # A change that changes nothing is not a version.
    assert change(client, {"offers": offers[:1]}, 2).data["changed"] == []
    assert AssistantProfileVersion.all_objects.count() == 2


def test_a_repeated_key_answers_the_first_save_and_is_refused_for_another() -> None:
    client = manager("profile-key")
    changes = {"company": {"name": said("Salon Ania")}}
    first = change(client, changes, 0, key="k1")

    again = change(client, changes, 0, key="k1")
    other = change(client, {"company": {"name": said("Salon Ola")}}, 0, key="k1")

    assert (first.status_code, again.status_code) == (200, 200)
    assert again.data["version"] == 1
    assert (other.status_code, other.data["code"]) == (409, "assistant_idempotency_conflict")
    assert AssistantProfileVersion.all_objects.count() == 1


def test_a_preview_answers_what_the_save_would_leave_and_saves_nothing() -> None:
    client = manager("profile-preview")

    seen = change(client, {"company": {"name": said("Salon Ania")}}, 0, preview=True)

    assert seen.status_code == 200, seen.data
    assert (seen.data["version"], seen.data["changed"]) == (1, ["company.name"])
    assert not AssistantProfileVersion.all_objects.exists()
    assert change(client, {}, 3, preview=True).status_code == 409


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"company": {"name": said("Salon Ania", origin="guess")}}, "changes.company.name.origin"),
        ({"company": {"name": "Salon Ania"}}, "changes.company.name"),
        ({"owner": "Ania"}, "changes"),
        # A section and a field inside it both wrong: the section is named.
        ({"company": {"name": "Salon Ania", "owner": "Ania"}}, "changes.company"),
        (
            {"offers": [{"key": "cut", "people": said(["ania"])}]},
            "changes.offers.0.people.value",
        ),
        (
            {"places": [{"key": "salon"}, {"key": "salon"}]},
            "changes.places.1.key",
        ),
    ],
)
def test_what_is_not_a_profile_is_refused_by_field(changes: dict[str, Any], field: str) -> None:
    client = manager(f"profile-bad-{abs(hash(field)) % 10_000}")

    refused = change(client, changes, 0)

    assert refused.status_code == 400, refused.data
    assert field in [error["field"] for error in refused.data["errors"]]
    assert not AssistantProfileVersion.all_objects.exists()


def test_only_who_manages_the_company_reads_and_changes_it() -> None:
    # A team member talks to the assistant but does not manage the company.
    staff = manager("profile-staff", role_key="staff")
    assert staff.get(URL).status_code == 403
    assert change(staff, {"company": {"name": said("Salon")}}, 0).status_code == 403

    outside = manager("profile-plan", in_plan=False)
    assert outside.get(URL).data["code"] == "assistant_not_in_plan"
    assert change(outside, {}, 0).data["code"] == "assistant_not_in_plan"


def _owner(slug: str) -> TenantContext:
    manager(slug)
    membership = Membership.objects.get(organization__slug=slug)
    return context_for(membership)


def test_a_change_through_the_assistant_names_its_conversation() -> None:
    person = _owner("profile-acting")
    conversation = uuid4()
    acting = acting_context(person, via="assistant", ref=f"conversation:{conversation}")

    with activate_tenant_context(acting):
        saved = save_profile(
            changes={"company": {"activity": said("fryzjer damski", origin="assistant")}},
            expected_version=0,
            idempotency_key="step-1",
        )
        assert read_profile().version == saved.version == 1

    row = AssistantProfileVersion.all_objects.get()
    assert (row.acting_via, row.conversation_id) == ("assistant", conversation)


def test_another_company_has_its_own_profile() -> None:
    first, second = manager("profile-a"), manager("profile-b")
    assert change(first, {"company": {"name": said("Salon Ania")}}, 0).status_code == 200

    assert second.get(URL).data["version"] == 0
    assert change(second, {"company": {"name": said("Domki")}}, 0).data["version"] == 1
    assert sorted(
        AssistantProfileVersion.all_objects.values_list("organization__slug", "version")
    ) == [("profile-a", 1), ("profile-b", 1)]
    assert Organization.objects.count() == 2
