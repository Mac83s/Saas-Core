"""The company's word on its online booking and on who hears about it (R3a B3,
B9, W8; ADR-078): how far ahead the form offers, which contact it requires,
and whether the people who manage bookings are told."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.models import Membership, Role, RoleScope
from saas_core.modules.core.organizations.permissions import SYSTEM_ROLE_PERMISSIONS
from saas_core.modules.core.organizations.settings_service import change_settings, read_group
from saas_core.modules.shared.booking.models import PublicBookingRoute
from saas_core.modules.shared.notifications.models import AppNotification, NotificationMessage
from test_booking import _no_delivery, catalog, membership, tenant

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _fresh_throttle() -> Any:
    # The public form is throttled per client address: no test spends
    # another's allowance.
    cache.clear()
    yield
    cache.clear()


ONLINE = "booking.online"
NOTICES = "booking.notices"


def _change(group: str, key: str, **changes: Any) -> Any:
    return change_settings(
        group, changes=changes, expected_version=read_group(group).version, idempotency_key=key
    )


def _public(member: Membership, slug: str) -> tuple[APIClient, str, dict[str, Any]]:
    configured = catalog(member)
    PublicBookingRoute.objects.create(public_slug=slug, organization_id=member.organization_id)
    query = {
        "service_id": str(configured["service"].id),
        "location_id": str(configured["location"].id),
    }
    return APIClient(), f"/api/v1/booking/public/{slug}", {**configured, "query": query}


def _book(client: APIClient, url: str, configured: dict[str, Any], customer: dict[str, str]) -> Any:
    day = str(configured["date"])
    times = client.get(f"{url}/slots/", {**configured["query"], "from": day, "to": day})
    return client.post(
        f"{url}/appointments/",
        {
            **configured["query"],
            "starts_at": times.json()["items"][0]["starts_at"],
            "customer": customer,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"book-{customer.get('display_name')}",
    )


def _manager(owner: Membership) -> Membership:
    user = User.objects.create_user(email="recepcja@example.test")
    user.status = UserStatus.ACTIVE
    user.save()
    role, _ = Role.objects.get_or_create(
        key="manager",
        organization=None,
        organization_type="",
        defaults={
            "name": "Manager",
            "scope": RoleScope.SYSTEM,
            "permissions": list(SYSTEM_ROLE_PERMISSIONS["manager"]),
            "is_immutable": True,
        },
    )
    return Membership.objects.create(organization=owner.organization, user=user, role=role)


def test_the_form_offers_only_the_company_s_horizon(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_delivery(monkeypatch)
    member = membership("online-horizon")
    client, url, configured = _public(member, "horyzont")
    day = str(configured["date"])  # a week from today
    assert client.get(f"{url}/").json()["online"]["horizon_days"] == 15
    assert client.get(f"{url}/slots/", {**configured["query"], "from": day, "to": day}).json()[
        "items"
    ]
    starts_at = client.get(f"{url}/slots/", {**configured["query"], "from": day, "to": day}).json()[
        "items"
    ][0]["starts_at"]

    with tenant(member):
        _change(ONLINE, "h-1", horizon_days=3)
    online = client.get(f"{url}/").json()["online"]
    # The company's day, not the server's: between midnight in Warsaw and
    # midnight UTC they are two different dates.
    today = member.organization.local_today()
    days = client.get(f"{url}/days/", {**configured["query"], "from": str(today), "to": day})
    later = client.get(f"{url}/times/", {**configured["query"], "date": day})
    refused = client.post(
        f"{url}/appointments/",
        {
            **configured["query"],
            "starts_at": starts_at,
            "customer": {"display_name": "Anna", "email": "anna@example.test"},
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="horyzont-1",
    )

    assert online["last_day"] == str(today + timedelta(days=2))
    assert all(item <= online["last_day"] for item in days.json()["items"])
    assert later.json()["items"] == []
    assert (refused.status_code, refused.json()["code"]) == (409, "beyond_booking_horizon")


def test_the_form_asks_for_the_contact_the_company_requires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    member = membership("online-contact")
    client, url, configured = _public(member, "kontakt")
    without_email = _book(client, url, configured, {"display_name": "Bez maila", "phone": "600"})
    assert without_email.status_code == 400
    assert without_email.json()["errors"][0]["field"] == "customer.email"

    with tenant(member):
        _change(ONLINE, "c-1", contact="phone")
    by_phone = _book(client, url, configured, {"display_name": "Z telefonem", "phone": "601"})
    assert client.get(f"{url}/").json()["online"]["contact"] == "phone"
    assert by_phone.status_code == 201


def test_the_office_hears_of_online_bookings_and_cancellations_when_the_company_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_delivery(monkeypatch)
    owner = membership("online-office")
    manager = _manager(owner)
    client, url, configured = _public(owner, "biuro")

    quiet = _book(client, url, configured, {"display_name": "Cicho", "email": "a@example.test"})
    assert quiet.status_code == 201
    assert not AppNotification.all_objects.filter(kind="booking.office_new").exists()

    with tenant(owner):
        _change(NOTICES, "o-1", office=True)
    # The same weekday a week later: the hours repeat.
    configured["date"] += timedelta(days=7)
    told = _book(client, url, configured, {"display_name": "Głośno", "email": "b@example.test"})
    assert told.status_code == 201
    new = AppNotification.all_objects.filter(kind="booking.office_new")
    assert {notice.user_id for notice in new} == {owner.user_id, manager.user_id}
    assert NotificationMessage.all_objects.filter(
        template_key="booking.office_new", recipient_email="recepcja@example.test"
    ).exists()

    token = told.json()["self_service_token"]
    canceled = client.post(
        f"/api/v1/booking/self-service/{token}/cancel/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="biuro-odwolanie",
    )
    assert canceled.status_code == 200
    assert {
        notice.user_id
        for notice in AppNotification.all_objects.filter(kind="booking.office_canceled")
    } == {owner.user_id, manager.user_id}
