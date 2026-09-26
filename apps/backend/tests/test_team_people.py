"""The company's people (ADR-058 §1, §9): one entry per person, with an account
or without one, their services and hours, and who may see and change what.

Phase 2 of the team plan: the list and the card. The rules under test are the
owner's (answers 3, 5 and 7 of 24.09; the plan's acceptance of 26.09).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserSession, UserStatus
from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.joining import SeatLimitReached, current_seat_usage
from saas_core.modules.core.organizations.models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipStatus,
    Organization,
    OrganizationAuditEntry,
    Role,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    Feature,
    SubscriptionState,
)
from saas_core.modules.shared.booking.models import (
    AvailabilityRule,
    Location,
    Service,
    ServiceLocation,
    StaffMember,
)
from saas_core.modules.shared.booking.services import cancel_appointment, update_staff
from saas_core.modules.shared.booking.staff import (
    StaffHasUpcomingAppointments,
    add_person,
    add_time_off,
    end_person,
    invite_person,
    list_people,
    people_day,
    person_detail,
    remove_time_off,
    restore_person,
    set_person_hours,
)
from test_booking import catalog, create, membership, tenant
from test_organization_lifecycle import (
    ACCEPT_URL,
    INVITATIONS_URL,
    MEMBERS_URL,
    active_user,
    authenticated_member,
    csrf_value,
    invitation_token,
    login,
)

pytestmark = pytest.mark.django_db

STAFF_URL = "/api/v1/booking/staff/"


@pytest.fixture(autouse=True)
def clear_throttles() -> None:
    # Logins are throttled per client address, and every test logs in.
    cache.clear()


def member_of(owner: Membership, email: str, role_key: str) -> Membership:
    user = User.objects.create_user(email=email)
    user.status = UserStatus.ACTIVE
    user.save()
    return Membership.objects.create(
        organization=owner.organization,
        user=user,
        role=Role.objects.get(key=role_key, organization=None, organization_type=""),
    )


def acting(member: Membership) -> HttpRequest:
    request = RequestFactory().post("/")
    request.user = member.user
    return request


def bookable(organization: Organization, **quotas: int) -> None:
    Feature.objects.get_or_create(
        key="booking.enabled", defaults={"name": "Rezerwacje", "module": "shared.booking"}
    )
    EntitlementSnapshot.all_objects.update_or_create(
        organization=organization,
        defaults={
            "subscription_state": SubscriptionState.ACTIVE,
            "access_mode": AccessMode.FULL,
            "features": {"booking.enabled": True},
            "quotas": quotas,
            "sources": {"booking.enabled": {"kind": "plan"}},
        },
    )


def seats(owner: Membership, limit: int) -> None:
    EntitlementSnapshot.all_objects.filter(organization_id=owner.organization_id).update(
        quotas={"team_members.max": limit}
    )


def test_an_entry_cannot_name_another_organizations_invitation() -> None:
    owner = membership("gospodarz")
    other = membership("obca")
    with tenant(other):
        invitation = Invitation.objects.create(
            organization=other.organization,
            email="ktos@example.test",
            role=Role.objects.get(key="staff", organization=None, organization_type=""),
            token_hash="a" * 64,
            invited_by=other.user,
            expires_at=timezone.now() + timedelta(days=7),
        )
    # The database guard, not only the service: the invitation is the other
    # organization's, so linking to it would join a person across tenants.
    with pytest.raises(IntegrityError), transaction.atomic():
        StaffMember.all_objects.create(
            organization_id=owner.organization_id,
            display_name="Podrzut",
            public_slug="podrzut",
            invitation_id=invitation.id,
        )


def test_a_subcontractor_is_added_with_services_and_hours_and_no_account() -> None:
    owner = membership("podwykonawca")
    configured = catalog(owner)
    service = configured["service"]
    with tenant(owner):
        ServiceLocation.all_objects.filter(service=service).delete()
        staff = add_person(
            request=acting(owner),
            name="Łukasz Nowak",
            phone="604 567 890",
            service_ids=[service.id],
            hours={"weekdays": [2, 0, 1], "local_start": time(7), "local_end": time(15)},
        )
        assert staff.public_slug == "lukasz-nowak"
        assert (staff.membership_id, staff.invitation_id, staff.phone) == (
            None,
            None,
            "604 567 890",
        )
        weekdays = AvailabilityRule.all_objects.filter(staff=staff, active=True).values_list(
            "weekday", flat=True
        )
        assert sorted(weekdays) == [0, 1, 2]
        # The service is offered where its new person works, as the settings
        # form always did alongside the hours.
        assert ServiceLocation.all_objects.filter(
            service=service, location=configured["location"]
        ).exists()
        person = {item.staff.id: item for item in list_people()}[staff.id]
        assert (person.service_ids, person.has_hours) == ([service.id], True)

        copy = add_person(request=acting(owner), name="Łukasz Nowak", copy_hours_from=staff.id)
        assert copy.public_slug == "lukasz-nowak-2"
        assert AvailabilityRule.all_objects.filter(staff=copy, active=True).count() == 3
    entry = OrganizationAuditEntry.objects.get(action="booking.staff.added", target_id=staff.id)
    assert entry.metadata == {"account": "none", "services": 1, "hours": 3}


def test_hours_replace_the_week_and_refuse_what_cannot_be_worked() -> None:
    owner = membership("godziny")
    configured = catalog(owner)
    staff: Any = configured["staff"]
    location = configured["location"]
    rule = {"weekday": 0, "location_id": location.id}
    with tenant(owner):
        with pytest.raises(ValidationError, match="nachodzą"):
            set_person_hours(
                staff_id=staff.id,
                rules=[
                    {**rule, "local_start": time(8), "local_end": time(12)},
                    {**rule, "local_start": time(11), "local_end": time(16)},
                ],
            )
        with pytest.raises(ValidationError, match="po jej początku"):
            set_person_hours(
                staff_id=staff.id,
                rules=[{**rule, "local_start": time(12), "local_end": time(8)}],
            )
        before = AvailabilityRule.all_objects.get(staff=staff)
        detail = set_person_hours(
            staff_id=staff.id,
            rules=[
                {**rule, "local_start": time(8), "local_end": time(12)},
                {**rule, "local_start": time(13), "local_end": time(17)},
            ],
        )
        assert [(item.local_start, item.local_end) for item in detail.hours] == [
            (time(8), time(12)),
            (time(13), time(17)),
        ]
        # Switched off, not deleted: last month's offer stays readable.
        before.refresh_from_db()
        assert before.active is False
        with pytest.raises(ValidationError, match="miejsca pracy"):
            add_person(
                request=acting(owner),
                name="Bez miejsca",
                hours={
                    "weekdays": [1],
                    "local_start": time(8),
                    "local_end": time(9),
                    "location_id": Location.all_objects.create(
                        organization=owner.organization,
                        name="Stary",
                        public_slug="stary",
                        active=False,
                    ).id,
                },
            )


def test_an_account_takes_a_seat_of_the_plan_and_a_subcontractor_does_not() -> None:
    owner = membership("miejsca")
    seats(owner, 2)
    with tenant(owner):
        anna = add_person(
            request=acting(owner),
            name="Anna",
            invitation={"email": "anna@example.test", "role": "staff"},
        )
        assert Invitation.objects.get(pk=anna.invitation_id).email == "anna@example.test"
        with pytest.raises(SeatLimitReached):
            add_person(
                request=acting(owner),
                name="Piotr",
                invitation={"email": "piotr@example.test", "role": "staff"},
            )
        add_person(request=acting(owner), name="Krzysztof")
        assert current_seat_usage() == (2, 2)
    # All or nothing: the refused invitation left no entry behind.
    assert not StaffMember.all_objects.filter(display_name="Piotr").exists()


def test_a_suspended_account_frees_its_seat_and_coming_back_takes_one() -> None:
    owner = membership("zawieszeni")
    seats(owner, 2)
    worker = member_of(owner, "praca@example.test", "staff")
    from saas_core.modules.core.organizations.lifecycle import update_membership  # noqa: PLC0415

    with tenant(owner):
        update_membership(
            request=acting(owner), membership_id=worker.id, membership_status="suspended"
        )
        add_person(
            request=acting(owner),
            name="Nowy",
            invitation={"email": "nowy@example.test", "role": "staff"},
        )
        with pytest.raises(SeatLimitReached):
            update_membership(
                request=acting(owner), membership_id=worker.id, membership_status="active"
            )


def test_the_person_the_office_added_is_the_one_who_accepts_the_invitation() -> None:
    _, owner, owner_client = authenticated_member(
        email="biuro@example.test", role_key="owner", slug="zaproszenia"
    )
    bookable(owner.organization)
    added = owner_client.post(
        STAFF_URL,
        {
            "name": "Kamil Duda",
            "phone": "607 330 912",
            "invitation": {"email": "kamil@example.test", "role": "staff"},
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(owner_client),
    )
    assert added.status_code == 201, added.data
    staff = StaffMember.all_objects.get(pk=added.data["id"])
    first = Invitation.objects.get(pk=staff.invitation_id)
    # The first invitation runs out and the office sends a new one the usual way.
    Invitation.objects.filter(pk=first.pk).update(expires_at=timezone.now() - timedelta(days=1))
    resent = owner_client.post(
        INVITATIONS_URL,
        {"email": "kamil@example.test", "role": "staff"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(owner_client),
    )
    assert resent.status_code == 201

    kamil = active_user("kamil@example.test")
    kamil_client = APIClient(enforce_csrf_checks=True)
    assert login(kamil_client, kamil).status_code == 200
    accepted = kamil_client.post(
        ACCEPT_URL,
        {"token": invitation_token(Invitation.objects.get(pk=resent.data["id"]))},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(kamil_client),
    )
    assert accepted.status_code == 200

    staff.refresh_from_db()
    assert staff.membership_id == Membership.objects.get(user=kamil).id
    assert str(staff.invitation_id) == resent.data["id"]
    assert staff.display_name == "Kamil Duda"
    assert OrganizationAuditEntry.objects.filter(
        action="booking.staff.linked", target_id=staff.id
    ).exists()


@pytest.mark.parametrize("sells", [True, False])
def test_someone_invited_elsewhere_gets_an_entry_where_the_company_sells_services(
    sells: bool,
) -> None:
    _, owner, owner_client = authenticated_member(
        email=f"wlasciciel-{sells}@example.test", role_key="owner", slug=f"uslugi-{sells}"
    )
    if sells:
        Service.all_objects.create(
            organization=owner.organization,
            name="Korekcja",
            public_slug="korekcja",
            duration_minutes=60,
        )
    invited = owner_client.post(
        INVITATIONS_URL,
        {"email": f"marta-{sells}@example.test", "role": "staff"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(owner_client),
    )
    marta = active_user(f"marta-{sells}@example.test")
    marta.first_name, marta.last_name = "Marta", "Wiśniewska"
    marta.save()
    marta_client = APIClient(enforce_csrf_checks=True)
    assert login(marta_client, marta).status_code == 200
    accepted = marta_client.post(
        ACCEPT_URL,
        {"token": invitation_token(Invitation.objects.get(pk=invited.data["id"]))},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(marta_client),
    )
    assert accepted.status_code == 200
    entries = StaffMember.all_objects.filter(membership__user=marta)
    assert [entry.display_name for entry in entries] == (["Marta Wiśniewska"] if sells else [])


def test_the_team_sees_everyone_but_only_management_and_the_person_see_the_phone() -> None:
    owner = membership("widocznosc")
    configured = catalog(owner)
    worker = member_of(owner, "pracownik@example.test", "staff")
    viewer = member_of(owner, "podglad@example.test", "viewer")
    with tenant(owner):
        mine = add_person(request=acting(owner), name="Pracownik", membership_id=worker.id)
        update_staff(staff_id=mine.id, data={"phone": "601 234 567"})
        update_staff(staff_id=configured["staff"].id, data={"phone": "602 345 678"})
        assert {item.staff.id: item.private for item in list_people()} == {
            configured["staff"].id: True,
            mine.id: True,
        }
    with tenant(worker):
        people = {item.staff.id: item.private for item in list_people()}
        assert people == {configured["staff"].id: False, mine.id: True}
        assert [item.staff.id for item in list_people(mine=True)] == [mine.id]
    with tenant(viewer):
        # Without the team screen a person sees no one else, not even by id.
        assert list_people() == []
        with pytest.raises(NotFound):
            person_detail(configured["staff"].id)


def test_a_person_changes_their_own_phone_and_nothing_else_of_anyone() -> None:
    owner = membership("telefony")
    configured = catalog(owner)
    worker = member_of(owner, "sam@example.test", "staff")
    with tenant(owner):
        mine = add_person(request=acting(owner), name="Sam", membership_id=worker.id)
    with tenant(worker):
        update_staff(staff_id=mine.id, data={"phone": "605 000 111"})
        with pytest.raises(OrganizationPermissionDenied):
            update_staff(staff_id=mine.id, data={"display_name": "Ktoś inny"})
        with pytest.raises(OrganizationPermissionDenied):
            update_staff(staff_id=configured["staff"].id, data={"phone": "605 000 222"})
    entry = OrganizationAuditEntry.objects.get(action="booking.staff.updated", target_id=mine.id)
    # A phone number is personal data: the history says it changed, not to what.
    assert entry.metadata == {"changes": {"phone": {"changed": True}}}


def test_own_hours_and_time_off_need_the_products_permission() -> None:
    owner = membership("grafik")
    configured = catalog(owner)
    location = configured["location"]
    worker = member_of(owner, "grafik-sam@example.test", "staff")
    viewer = member_of(owner, "grafik-podglad@example.test", "viewer")
    with tenant(owner):
        mine = add_person(request=acting(owner), name="Ja", membership_id=worker.id)
        theirs = add_person(request=acting(owner), name="Oni", membership_id=viewer.id)
    week = [
        {"weekday": 3, "local_start": time(9), "local_end": time(17), "location_id": location.id}
    ]
    tomorrow = timezone.now() + timedelta(days=1)
    with tenant(worker):
        assert len(set_person_hours(staff_id=mine.id, rules=week).hours) == 1
        item, _ = add_time_off(
            staff_id=mine.id, starts_at=tomorrow, ends_at=tomorrow + timedelta(hours=8)
        )
        remove_time_off(time_off_id=item.id)
        with pytest.raises(OrganizationPermissionDenied):
            set_person_hours(staff_id=configured["staff"].id, rules=week)
    # Core's viewer has no `booking.schedule.own`: like HoofCare's trimmer,
    # their week is set by the office.
    with tenant(viewer), pytest.raises(OrganizationPermissionDenied):
        set_person_hours(staff_id=theirs.id, rules=week)


def test_an_absence_counts_the_visits_it_runs_into_and_hides_its_reason() -> None:
    owner = membership("urlopy")
    configured = catalog(owner)
    staff: Any = configured["staff"]
    worker = member_of(owner, "kolega@example.test", "staff")
    created = create(owner, configured)
    day = configured["date"]
    with tenant(owner):
        item, conflicts = add_time_off(
            staff_id=staff.id,
            starts_at=created.appointment.starts_at - timedelta(hours=1),
            ends_at=created.appointment.ends_at + timedelta(hours=1),
            reason="L4",
        )
        assert conflicts == 1
        _, _, rows = people_day(day)
        assert {row.staff_id: row.time_off[0][2] for row in rows if row.time_off} == {
            staff.id: "L4"
        }
        assert person_detail(staff.id).time_off == [item]
    with tenant(worker):
        _, _, rows = people_day(day)
        # A colleague sees the absence, never why: an illness is health data.
        assert [row.time_off[0][2] for row in rows if row.time_off] == [None]
        assert [row.busy for row in rows if row.staff_id == staff.id][0]
    entry = OrganizationAuditEntry.objects.get(action="booking.staff.time_off_added")
    assert "L4" not in str(entry.metadata)


def test_the_days_hours_are_instants_on_the_night_the_clocks_go_back() -> None:
    owner = membership("zmiana-czasu")
    configured = catalog(owner)
    staff: Any = configured["staff"]
    night = date(2026, 10, 25)  # Europe/Warsaw: 03:00 CEST becomes 02:00 CET
    with tenant(owner):
        set_person_hours(
            staff_id=staff.id,
            rules=[
                {
                    "weekday": night.weekday(),
                    "local_start": time(1),
                    "local_end": time(5),
                    "location_id": configured["location"].id,
                }
            ],
        )
        day, zone, rows = people_day(night)
    assert (day, zone) == (night, "Europe/Warsaw")
    works = next(row.works for row in rows if row.staff_id == staff.id)
    # 01:00 is summer time and 05:00 winter time: five hours of work, not four.
    assert works == [
        (datetime(2026, 10, 24, 23, tzinfo=UTC), datetime(2026, 10, 25, 4, tzinfo=UTC))
    ]


def test_removing_a_person_waits_for_their_visits_then_takes_the_account() -> None:
    owner = membership("koniec")
    configured = catalog(owner)
    staff: Any = configured["staff"]
    worker = member_of(owner, "odchodzi@example.test", "staff")
    with tenant(owner):
        update_staff(staff_id=staff.id, data={"membership_id": worker.id})
    created = create(owner, configured)
    with tenant(owner):
        with pytest.raises(StaffHasUpcomingAppointments, match=r"\(1\)"):
            end_person(request=acting(owner), staff_id=staff.id)
        cancel_appointment(
            appointment_id=created.appointment.id,
            idempotency_key="odwolanie",
            principal_ref=str(owner.user_id),
        )
        ended = end_person(request=acting(owner), staff_id=staff.id)
        assert ended.active is False
        worker.refresh_from_db()
        assert worker.status == MembershipStatus.REVOKED
        # Back on the team, without the account: that takes a new invitation.
        assert restore_person(staff_id=staff.id).active is True
    worker.refresh_from_db()
    assert worker.status == MembershipStatus.REVOKED


def test_inviting_a_person_again_replaces_the_invitation_still_waiting() -> None:
    owner = membership("ponownie")
    with tenant(owner):
        staff = add_person(
            request=acting(owner),
            name="Literówka",
            invitation={"email": "zly@example.test", "role": "staff"},
        )
        wrong = staff.invitation_id
        invitation = invite_person(
            request=acting(owner), staff_id=staff.id, email="dobry@example.test", role="staff"
        )
        staff.refresh_from_db()
        assert staff.invitation_id == invitation.id
        assert Invitation.objects.get(pk=wrong).status == InvitationStatus.REVOKED


def test_a_new_role_works_from_the_next_request_without_signing_anyone_out() -> None:
    _, admin, admin_client = authenticated_member(
        email="admin@example.test", role_key="admin", slug="bez-wylogowania"
    )
    manager, manager_membership, manager_client = authenticated_member(
        email="menedzer@example.test", role_key="manager", organization=admin.organization
    )
    assert manager_client.get(INVITATIONS_URL).status_code == 200
    changed = admin_client.patch(
        f"{MEMBERS_URL}{manager_membership.id}/",
        {"role": "viewer"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(admin_client),
    )
    assert changed.status_code == 200
    assert UserSession.objects.filter(user=manager, revoked_at__isnull=True).exists()
    # Permissions come from the role on every request: the downgrade already holds.
    assert manager_client.get("/api/v1/organizations/current/").data["role"] == "viewer"
    assert manager_client.get(INVITATIONS_URL).status_code == 403


def test_management_lists_former_members_and_the_seats_they_no_longer_take() -> None:
    _, owner, owner_client = authenticated_member(
        email="byli-wlasciciel@example.test", role_key="owner", slug="byli"
    )
    bookable(owner.organization, **{"team_members.max": 5})
    _, gone, _ = authenticated_member(
        email="byly@example.test", role_key="staff", organization=owner.organization
    )
    _, stays, stays_client = authenticated_member(
        email="zostaje@example.test", role_key="staff", organization=owner.organization
    )
    owner_client.patch(
        f"{MEMBERS_URL}{gone.id}/",
        {"status": "revoked"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(owner_client),
    )
    current = owner_client.get(MEMBERS_URL).data
    assert {item["email"] for item in current} == {
        "byli-wlasciciel@example.test",
        "zostaje@example.test",
    }
    everyone = owner_client.get(MEMBERS_URL, {"include_former": "true"}).data
    former = [item for item in everyone if item["status"] == "revoked"]
    assert [(item["email"], item["revoked_at"] is not None) for item in former] == [
        ("byly@example.test", True)
    ]
    # Former staff is personnel history: management's, not every colleague's.
    assert stays_client.get(MEMBERS_URL, {"include_former": "true"}).status_code == 403
    assert owner_client.get("/api/v1/organizations/current/seats/").data == {
        "used": 2,
        "limit": 5,
    }
    assert stays.status == MembershipStatus.ACTIVE


def test_the_people_api_answers_with_the_card_and_refuses_a_stranger() -> None:
    _, owner, owner_client = authenticated_member(
        email="api-wlasciciel@example.test", role_key="owner", slug="api-ludzie"
    )
    bookable(owner.organization)
    Location.all_objects.create(organization=owner.organization, name="Baza", public_slug="baza")
    headers = {"HTTP_X_CSRFTOKEN": csrf_value(owner_client)}
    added = owner_client.post(
        STAFF_URL,
        {
            "name": "Krzysztof Nowak",
            "phone": "604 567 890",
            "hours": {"weekdays": [0, 1, 2, 3, 4], "local_start": "06:00", "local_end": "16:00"},
        },
        format="json",
        **headers,
    )
    assert added.status_code == 201, added.data
    card = added.data
    assert (card["name"], card["phone"], card["membership_id"]) == (
        "Krzysztof Nowak",
        "604 567 890",
        None,
    )
    assert [rule["weekday"] for rule in card["hours"]] == [0, 1, 2, 3, 4]
    assert card["hours"][0]["location_name"] == "Baza"
    listed = owner_client.get(STAFF_URL).data["items"]
    assert [item["id"] for item in listed] == [card["id"]]
    today = owner_client.get("/api/v1/booking/staff-availability/").data
    assert [item["staff_id"] for item in today["items"]] == [card["id"]]
    assert owner_client.get("/api/v1/booking/appointments/", {"limit": 1}).status_code == 200

    _, stranger, stranger_client = authenticated_member(
        email="obcy@example.test", role_key="owner", slug="api-obcy"
    )
    bookable(stranger.organization)
    assert stranger_client.get(f"{STAFF_URL}{card['id']}/").status_code == 404
    refused = stranger_client.post(
        f"{STAFF_URL}{card['id']}/end/", HTTP_X_CSRFTOKEN=csrf_value(stranger_client)
    )
    assert refused.status_code == 404
