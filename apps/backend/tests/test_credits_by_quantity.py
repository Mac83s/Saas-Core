"""Credits by quantity: holds for N units, settlement of what was delivered (TL4, ADR-069 pkt 23).

Translations bill 1,000 characters × language and a job delivers part of what
it reserved, so a reservation carries a quantity and a unit price, and
`settle_credits` commits the delivered units — allowance first — and gives
back the rest in one transaction. A hold from last month's allowance that is
given back this month expires instead of topping this month up.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.shared.billing.credits import (
    CreditReservationConflict,
    credit_summary,
    operation_cost,
    release_credits,
    release_expired_credit_reservations,
    reserve_credits,
    settle_credits,
)
from saas_core.modules.shared.billing.models import (
    CreditLedgerEntry,
    CreditLedgerKind,
    CreditOperation,
    CreditReservation,
    CreditReservationState,
)
from test_billing_credits import NOW, assert_ledger_matches_balance, setup_credits

pytestmark = pytest.mark.django_db

OPERATION = "test.characters"


@pytest.fixture(autouse=True)
def metered_operation() -> None:
    CreditOperation.objects.update_or_create(
        key=OPERATION,
        defaults={"name": "Test", "cost": 3, "unit": "1000_characters", "is_active": True},
    )


def test_a_hold_for_n_units_records_the_quantity_and_the_unit_price() -> None:
    tenant, context, _ = setup_credits(slug="qty-hold", allowance=100)

    with activate_tenant_context(context):
        set_local_organization_id(tenant.id)
        held = reserve_credits(OPERATION, idempotency_key="job:1", quantity=7, at=NOW)
        again = reserve_credits(OPERATION, idempotency_key="job:1", quantity=7, at=NOW)
        with pytest.raises(CreditReservationConflict):
            reserve_credits(OPERATION, idempotency_key="job:1", quantity=8, at=NOW)

    assert held is not None and again is not None and again.id == held.id
    assert (held.quantity, held.unit_cost, held.cost) == (7, 3, 21)
    assert operation_cost(OPERATION, 7) == 21


def test_settling_part_commits_the_delivered_units_and_gives_back_the_rest() -> None:
    tenant, context, _ = setup_credits(slug="qty-settle", allowance=100)

    with activate_tenant_context(context):
        set_local_organization_id(tenant.id)
        reserve_credits(OPERATION, idempotency_key="job:2", quantity=10, at=NOW)
        settled = settle_credits("job:2", 4, at=NOW)
        repeated = settle_credits("job:2", 4, at=NOW)
        with pytest.raises(CreditReservationConflict):
            settle_credits("job:2", 5, at=NOW)
        summary = credit_summary(at=NOW)

    assert settled.state == CreditReservationState.COMMITTED
    assert repeated.settled_quantity == 4
    assert summary.allowance_remaining == 100 - 12
    assert summary.allowance_reserved == 0
    consumed = CreditLedgerEntry.all_objects.get(
        organization=tenant, kind=CreditLedgerKind.CONSUMED
    )
    assert (consumed.amount, consumed.operation_quantity, consumed.operation_cost) == (-12, 4, 3)
    assert_ledger_matches_balance(tenant)


def test_settling_nothing_is_a_release_and_works_after_the_hold_expired() -> None:
    tenant, context, _ = setup_credits(slug="qty-zero", allowance=100)

    with activate_tenant_context(context):
        set_local_organization_id(tenant.id)
        reserve_credits(
            OPERATION,
            idempotency_key="job:3",
            quantity=5,
            at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
        later = NOW + timedelta(hours=3)
        settled = settle_credits("job:3", 0, at=later)
        reserve_credits(
            OPERATION,
            idempotency_key="job:4",
            quantity=5,
            at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
        partial = settle_credits("job:4", 2, at=later)
        summary = credit_summary(at=later)

    assert settled.state == CreditReservationState.RELEASED
    assert partial.state == CreditReservationState.COMMITTED
    assert summary.allowance_remaining == 100 - 6
    assert summary.allowance_reserved == 0
    assert_ledger_matches_balance(tenant)


def test_last_months_allowance_given_back_this_month_expires_instead_of_adding_up() -> None:
    tenant, context, _ = setup_credits(slug="qty-rollover", allowance=100)
    next_month = NOW.replace(month=10, day=1)

    with activate_tenant_context(context):
        set_local_organization_id(tenant.id)
        reserve_credits(OPERATION, idempotency_key="job:5", quantity=10, at=NOW)  # 30 held
        reserve_credits(OPERATION, idempotency_key="job:6", quantity=10, at=NOW)  # 30 held
        settle_credits("job:5", 4, at=next_month)  # 12 spent, 18 released from September
        release_credits("job:6", at=next_month)  # 30 released from September
        summary = credit_summary(at=next_month)

    # October's own 100 and nothing of September's.
    assert summary.allowance_remaining == 100
    assert summary.allowance_reserved == 0
    expired = CreditLedgerEntry.all_objects.filter(
        organization=tenant, kind=CreditLedgerKind.ALLOWANCE_EXPIRED
    ).exclude(reservation=None)
    assert sorted(entry.amount for entry in expired) == [-30, -18]
    assert_ledger_matches_balance(tenant)


def test_the_sweep_expires_an_abandoned_hold_from_last_month() -> None:
    tenant, context, _ = setup_credits(slug="qty-sweep", allowance=100)
    next_month = NOW.replace(month=10, day=1)

    with activate_tenant_context(context):
        set_local_organization_id(tenant.id)
        reserve_credits(
            OPERATION,
            idempotency_key="job:7",
            quantity=5,
            at=NOW,
            expires_at=NOW + timedelta(days=1),
        )

    assert release_expired_credit_reservations(at=next_month) == 1
    with activate_tenant_context(context):
        summary = credit_summary(at=next_month)
    assert summary.allowance_remaining == 100
    assert (
        CreditReservation.all_objects.get(idempotency_key="job:7").state
        == CreditReservationState.RELEASED
    )
    assert_ledger_matches_balance(tenant)


def test_the_credits_page_lists_movements_with_their_units() -> None:
    from saas_core.modules.core.identity.models import UserStatus
    from saas_core.modules.core.organizations.models import Membership, Role

    tenant, context, actor = setup_credits(slug="qty-ledger", allowance=100)
    with activate_tenant_context(context):
        set_local_organization_id(tenant.id)
        reserve_credits(OPERATION, idempotency_key="job:8", quantity=10, at=NOW)
        settle_credits("job:8", 4, at=NOW)
    actor.set_password("Bezpieczne-Haslo-2026!")
    actor.status = UserStatus.ACTIVE
    actor.save()
    Membership.objects.create(
        organization=tenant,
        user=actor,
        role=Role.objects.get(key="owner", organization=None, organization_type=""),
    )
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf/").data["csrf_token"]
    assert (
        client.post(
            "/api/v1/auth/login/",
            {"email": actor.email, "password": "Bezpieczne-Haslo-2026!"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        ).status_code
        == 200
    )

    page = client.get("/api/v1/billing/credits/ledger/?limit=1")
    rest = client.get(f"/api/v1/billing/credits/ledger/?cursor={page.data['next_cursor']}")

    assert page.status_code == 200, page.data
    first = page.data["items"][0]
    assert (first["kind"], first["amount"], first["operation_quantity"]) == ("consumed", -12, 4)
    assert page.data["next_cursor"] is not None
    assert [item["kind"] for item in rest.data["items"]] == ["allowance_granted"]
    # The row names its operation from the catalogue; nobody registered what
    # this one is for, so there is nothing to open. A grant is no operation.
    operation = CreditOperation.objects.get(key=OPERATION)
    assert (first["operation_name"], first["operation_unit"], first["subject"]) == (
        operation.name,
        operation.unit,
        None,
    )
    assert (rest.data["items"][0]["operation_name"], rest.data["items"][0]["subject"]) == ("", None)
    # „Zużycie” is the server's filter, and an unknown kind is refused on its field.
    consumed = client.get("/api/v1/billing/credits/ledger/?kind=consumed")
    assert [item["kind"] for item in consumed.data["items"]] == ["consumed"]
    assert consumed.data["next_cursor"] is None
    refused = client.get("/api/v1/billing/credits/ledger/?kind=spent")
    assert refused.status_code == 400
    assert [error["field"] for error in refused.json()["errors"]] == ["kind"]


def test_the_owner_of_an_operation_says_what_a_row_was_for() -> None:
    """Billing knows no module by name: the operation's owner registers how a
    hold's key names the thing it paid for (a translation job)."""
    from saas_core.modules.shared.billing import credits

    assert credits.credit_subject(OPERATION, "job:8") is None
    credits.register_credit_subject(OPERATION, lambda key: ("testing.job", key.partition(":")[2]))
    try:
        assert credits.credit_subject(OPERATION, "job:8") == {"kind": "testing.job", "id": "8"}
        # A movement without a hold (a grant, a purchase) has nothing to open.
        assert credits.credit_subject(OPERATION, "") is None
    finally:
        credits._subject_resolvers.pop(OPERATION, None)
