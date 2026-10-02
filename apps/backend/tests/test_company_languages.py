"""The company's languages: one service changes them (ADR-071 pkt 4–7, ADR-078 pkt 5,
7, 9; plan TL10). A preview that writes nothing, a key and a version of their own,
history and one audit row, the plan's limit only when adding, a site's source
language kept, and removing as a person's decision."""

from __future__ import annotations

from typing import Any
from uuid import uuid7

import pytest
from django.core.cache import cache
from django.test import override_settings

from saas_core.modules.core.organizations.context import (
    acting_context,
    activate_tenant_context,
    context_from_membership,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
    PublicLocalesChange,
    WorkspaceKind,
)
from saas_core.modules.core.organizations.person_gate import PersonRequired
from saas_core.modules.core.organizations.public_locales import change_public_locales
from saas_core.modules.shared.billing.models import AccessMode, EntitlementSnapshot, Plan
from test_sites_api import csrf_value, sites_client

pytestmark = pytest.mark.django_db
URL = "/api/v1/organizations/current/public-locales/"
QUOTA = "public_locales.additional.max"


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def _company(slug: str, *, locales: list[str] | None = None, **snapshot: Any) -> tuple[Any, Any]:
    client, organization, _ = sites_client(slug=slug, role_key="owner")
    Organization.objects.filter(pk=organization.pk).update(public_locales=locales or ["pl"])
    if snapshot:
        EntitlementSnapshot.all_objects.filter(organization=organization).update(**snapshot)
    return client, organization


def _send(client: Any, method: str, url: str, payload: dict[str, Any], key: str = "") -> Any:
    return getattr(client, method)(
        url,
        payload,
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        **({"HTTP_IDEMPOTENCY_KEY": key} if key else {}),
    )


def _change(client: Any, locales: list[str], version: int, key: str = "change") -> Any:
    return _send(client, "put", URL, {"public_locales": locales, "expected_version": version}, key)


def _codes(response: Any) -> set[tuple[str, str]]:
    return {(error["field"], error["code"]) for error in response.data["errors"]}


def test_a_change_is_previewed_saved_once_and_recorded_with_its_own_version():
    client, organization = _company("lang-change")
    read = client.get(URL)
    assert (read.data["public_locales"], read.data["version"]) == (["pl"], 0)
    assert [item["code"] for item in read.data["offered"]] == ["pl", "en"]

    preview = _send(
        client, "post", URL + "preview/", {"public_locales": ["pl", "en"], "expected_version": 0}
    )
    keyless = _change(client, ["pl", "en"], 0, key="")
    saved = _change(client, ["pl", "en"], 0)
    again = _change(client, ["pl", "en"], 0)
    other = _change(client, ["en", "pl"], 1, key="other")
    reused = _change(client, ["en", "pl"], 1, key="change")
    stale = _change(client, ["en", "pl"], 0, key="stale")

    assert preview.status_code == 200, preview.data
    assert (preview.data["added"], preview.data["version"]) == (["en"], 1)
    assert keyless.status_code == 400
    assert saved.status_code == 200, saved.data
    assert again.data == saved.data
    assert other.status_code == 200, other.data
    assert reused.status_code == 409
    assert reused.data["code"] == "settings_idempotency_conflict"
    assert stale.status_code == 409
    assert stale.data["code"] == "settings_version_conflict"
    organization.refresh_from_db()
    assert (organization.public_locales, organization.public_locales_version) == (["en", "pl"], 2)
    # The company's own version is untouched: an open form of its name or
    # time zone stays valid.
    assert organization.version == 1
    history = list(
        PublicLocalesChange.objects.filter(organization=organization).order_by("version")
    )
    assert [(row.before, row.after, row.origin) for row in history] == [
        (["pl"], ["pl", "en"], "settings"),
        (["pl", "en"], ["en", "pl"], "settings"),
    ]
    audit = OrganizationAuditEntry.objects.filter(
        organization=organization, action="organization.settings_changed"
    ).order_by("occurred_at")
    assert [row.target_type for row in audit] == ["organization.public_locales"] * 2
    assert audit.first().metadata["changes"] == {
        "public_locales": {"from": ["pl"], "to": ["pl", "en"]}
    }
    history = client.get("/api/v1/organizations/current/history/").data["items"]
    languages = next(
        item for item in history if item["target_type"] == "organization.public_locales"
    )
    assert languages["changes"] == {"public_locales": {"from": ["pl", "en"], "to": ["en", "pl"]}}
    assert "changes" not in languages["details"]


def test_wrong_lists_are_refused_field_by_field():
    client, _ = _company("lang-wrong")

    repeated = _change(client, ["pl", "pl"], 0, key="repeated")
    unknown = _change(client, ["pl", "xx"], 0, key="unknown")
    elsewhere = _change(client, ["pl", "de"], 0, key="elsewhere")
    empty = _change(client, [], 0, key="empty")

    assert ("public_locales", "duplicate") in _codes(repeated)
    assert any(code == "locale_not_in_registry" for _field, code in _codes(unknown))
    # Registered, but not a language of this product.
    assert ("public_locales", "locale_not_supported") in _codes(elsewhere)
    assert empty.status_code == 400
    assert not PublicLocalesChange.objects.exists()


@override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de"))
def test_the_plan_limits_adding_and_never_removing_or_reordering():
    client, organization = _company("lang-limit", quotas={QUOTA: 1})

    first = _change(client, ["pl", "en"], 0, key="first")
    second = _change(client, ["pl", "en", "de"], 1, key="second")
    reordered = _change(client, ["en", "pl"], 1, key="reordered")
    removed = _change(client, ["en"], 2, key="removed")

    assert first.status_code == 200, first.data
    assert ("public_locales", "quota_exceeded") in _codes(second)
    assert reordered.status_code == 200, reordered.data
    assert removed.status_code == 200, removed.data
    # A plan of zero refuses the second language too.
    EntitlementSnapshot.all_objects.filter(organization=organization).update(quotas={QUOTA: 0})
    assert ("public_locales", "quota_exceeded") in _codes(
        _change(client, ["en", "pl"], 3, key="zero")
    )


def test_a_subscription_that_cannot_write_refuses_adding_with_its_reason():
    client, _ = _company("lang-read-only", locales=["pl", "en"], access_mode=AccessMode.READ_ONLY)

    reordered = _change(client, ["en", "pl"], 0, key="reordered")
    removed = _change(client, ["en"], 1, key="removed")
    added = _change(client, ["en", "pl"], 2, key="added")

    assert reordered.status_code == 200, reordered.data
    assert removed.status_code == 200, removed.data
    assert ("public_locales", "plan_access_denied") in _codes(added)
    assert "tylko do odczytu" in added.data["errors"][0]["message"]


def test_the_platform_workspace_has_no_limit():
    _, organization = _company("lang-platform", quotas={QUOTA: 0})
    Organization.objects.filter(pk=organization.pk).update(workspace_kind=WorkspaceKind.PLATFORM)
    membership = Membership.objects.get(organization=organization)

    with activate_tenant_context(context_from_membership(membership)):
        plan = change_public_locales(
            locales=["pl", "en"], expected_version=0, idempotency_key="platform"
        )

    assert plan.change is not None


def _english_site(client: Any) -> Any:
    return _send(
        client,
        "post",
        "/api/v1/sites/",
        {"name": "English site", "slug": "english-site", "default_locale": "en"},
        key="english-site",
    )


def test_a_site_s_source_language_stays_and_a_new_site_adds_its_language():
    client, organization = _company("lang-site")

    created = _english_site(client)
    # The site's language is the company's now, through the same history.
    assert created.status_code == 201, created.data
    organization.refresh_from_db()
    assert organization.public_locales == ["en", "pl"]
    (change,) = PublicLocalesChange.objects.filter(organization=organization)
    assert (change.origin, change.after) == ("site_source", ["en", "pl"])

    removed = _change(client, ["pl"], organization.public_locales_version)
    assert ("public_locales", "site_default_not_removable") in _codes(removed)
    read = client.get(URL)
    assert read.data["protected"] == {"en": "site_default_not_removable"}


def test_a_new_site_beyond_the_plan_is_refused_on_its_language():
    client, _ = _company("lang-site-limit", quotas={QUOTA: 0, "sites.max": 3})

    refused = _english_site(client)

    assert refused.status_code == 400
    assert ("default_locale", "quota_exceeded") in _codes(refused)


def test_removing_a_language_is_a_person_s_decision():
    _, organization = _company("lang-person", locales=["pl", "en"])
    membership = Membership.objects.get(organization=organization)
    acting = acting_context(
        context_from_membership(membership), via="assistant", ref=f"conversation:{uuid7()}"
    )

    with activate_tenant_context(acting):
        preview = change_public_locales(
            locales=["pl"], expected_version=0, idempotency_key="", preview=True
        )
        with pytest.raises(PersonRequired):
            change_public_locales(locales=["pl"], expected_version=0, idempotency_key="remove")
        reordered = change_public_locales(
            locales=["en", "pl"], expected_version=0, idempotency_key="reorder"
        )

    assert preview.person_gates == {"Usunięcie języka firmy"}
    assert reordered.change is not None


def test_only_the_cheapest_plan_carries_the_limit():
    quotas = {
        plan.key: plan.current_version.quotas.get(QUOTA)
        for plan in Plan.objects.select_related("current_version").filter(
            key__in=["profile", "starter", "pro"]
        )
    }
    assert quotas == {"profile": 1, "starter": None, "pro": None}
