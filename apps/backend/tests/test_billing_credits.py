"""Credits: a prepaid pool our customers spend on metered operations.

The ledger is the truth and the balance row is its cached sum, so most of what
matters here is that the two cannot drift: every test that moves credits ends
by rebuilding the balance from the entries. The rest is the shape of the
promise — the plan's monthly allowance resets, purchased credits do not, and
spending takes the allowance first so nobody loses what they paid for.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.db import DatabaseError, connection, transaction

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    Organization,
    OrganizationAuditAction,
    OrganizationAuditEntry,
)
from saas_core.modules.shared.billing.credits import (
    CreditPurchaseConflict,
    CreditReservationConflict,
    CreditReservationExpired,
    CreditsExhausted,
    CreditsUnavailable,
    UnknownCreditOperation,
    commit_credits,
    complete_credit_purchase,
    credit_summary,
    grant_operator_credits,
    refresh_credit_allowances,
    refund_credits,
    release_credits,
    release_expired_credit_reservations,
    reserve_credits,
    spend_credits,
    start_credit_purchase,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    CreditBalance,
    CreditBucket,
    CreditLedgerEntry,
    CreditLedgerKind,
    CreditOperation,
    CreditPurchase,
    CreditPurchaseStatus,
    CreditReservation,
    CreditReservationState,
    EntitlementSnapshot,
    Plan,
    SubscriptionState,
)

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


def setup_credits(
    *,
    slug: str,
    allowance: int = 200,
    access_mode: str = AccessMode.FULL,
) -> tuple[Organization, TenantContext, User]:
    tenant = Organization.objects.create(name=slug, slug=slug)
    actor = User.objects.create_user(email=f"{slug}@example.com")
    # The snapshot is where an allowance actually comes from, whether the plan
    # version declares it or an operator override grants it. The seeded pilot
    # versions do not declare it yet (a published version is immutable), so
    # these tests put it in the snapshot directly — which is exactly what the
    # code reads.
    plan_version = Plan.objects.get(key="starter").current_version
    EntitlementSnapshot.all_objects.create(
        organization=tenant,
        plan_version=plan_version,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=access_mode,
        features={"sites.enabled": True},
        quotas={"credits.monthly": allowance},
        sources={"credits.monthly": {"kind": "plan"}},
    )
    return (
        tenant,
        TenantContext(
            organization_id=tenant.id,
            membership_id=uuid.uuid7(),
            actor_id=actor.id,
            role_key="owner",
            permissions=frozenset(),
        ),
        actor,
    )


def assert_ledger_matches_balance(organization: Organization) -> None:
    """The invariant the whole design rests on."""
    balance = CreditBalance.all_objects.get(organization=organization)
    for bucket, remaining in (
        (CreditBucket.ALLOWANCE, balance.allowance_remaining),
        (CreditBucket.PURCHASED, balance.purchased_remaining),
    ):
        total = sum(
            entry.amount
            for entry in CreditLedgerEntry.all_objects.filter(
                organization=organization, bucket=bucket
            )
        )
        assert total == remaining, f"ledger {bucket} = {total}, saldo = {remaining}"


def test_the_plan_allowance_arrives_on_first_read_and_matches_the_ledger() -> None:
    tenant, context, _ = setup_credits(slug="credits-allowance", allowance=200)

    with activate_tenant_context(context):
        summary = credit_summary(at=NOW)

    assert summary.allowance_remaining == 200
    assert summary.allowance_granted == 200
    assert summary.purchased_remaining == 0
    assert summary.available == 200
    assert summary.allowance_period_start == NOW.date().replace(day=1)
    entry = CreditLedgerEntry.all_objects.get(organization=tenant)
    assert entry.kind == CreditLedgerKind.ALLOWANCE_GRANTED
    assert entry.amount == 200
    assert entry.balance_after == 200
    assert_ledger_matches_balance(tenant)


def test_reading_twice_does_not_grant_the_allowance_twice() -> None:
    tenant, context, _ = setup_credits(slug="credits-once", allowance=50)

    with activate_tenant_context(context):
        credit_summary(at=NOW)
        second = credit_summary(at=NOW + timedelta(hours=3))

    assert second.allowance_remaining == 50
    assert CreditLedgerEntry.all_objects.filter(organization=tenant).count() == 1


def test_spending_takes_the_allowance_before_anything_bought() -> None:
    """The promise: a month boundary never eats what somebody paid for."""
    tenant, context, _ = setup_credits(slug="credits-order", allowance=5)

    with activate_tenant_context(context):
        purchase = start_credit_purchase("credits-100", idempotency_key="buy:1")
        complete_credit_purchase(
            organization_id=tenant.id,
            purchase_id=purchase.id,
            provider_reference="sim_ref_1",
            at=NOW,
        )
        # assistant.generate_draft costs 10, the allowance holds 5.
        spend_credits("assistant.generate_draft", idempotency_key="draft:1", at=NOW)
        summary = credit_summary(at=NOW)

    assert summary.allowance_remaining == 0
    assert summary.purchased_remaining == 95
    consumed = CreditLedgerEntry.all_objects.filter(
        organization=tenant, kind=CreditLedgerKind.CONSUMED
    )
    assert {entry.bucket: entry.amount for entry in consumed} == {
        CreditBucket.ALLOWANCE: -5,
        CreditBucket.PURCHASED: -5,
    }
    assert_ledger_matches_balance(tenant)


def test_running_out_refuses_the_operation_and_leaves_the_balance_alone() -> None:
    tenant, context, _ = setup_credits(slug="credits-empty", allowance=1)

    with activate_tenant_context(context):
        with pytest.raises(CreditsExhausted):
            spend_credits("assistant.generate_draft", idempotency_key="draft:too-big", at=NOW)
        summary = credit_summary(at=NOW)

    assert summary.allowance_remaining == 1
    assert summary.available == 1
    assert not CreditReservation.all_objects.filter(organization=tenant).exists()
    assert_ledger_matches_balance(tenant)


def test_a_reservation_holds_credits_and_a_release_gives_them_back() -> None:
    """An AI call that times out must not bill anybody."""
    tenant, context, _ = setup_credits(slug="credits-release", allowance=20)

    with activate_tenant_context(context):
        reservation = reserve_credits(
            "assistant.generate_draft", idempotency_key="draft:hold", at=NOW
        )
        assert reservation is not None
        held = credit_summary(at=NOW)
        assert held.available == 10
        assert held.allowance_remaining == 20

        replay = reserve_credits("assistant.generate_draft", idempotency_key="draft:hold", at=NOW)
        assert replay is not None
        assert replay.id == reservation.id

        release_credits("draft:hold")
        after = credit_summary(at=NOW)

    assert after.available == 20
    assert CreditReservation.all_objects.get(pk=reservation.pk).state == (
        CreditReservationState.RELEASED
    )
    assert not CreditLedgerEntry.all_objects.filter(
        organization=tenant, kind=CreditLedgerKind.CONSUMED
    ).exists()
    assert_ledger_matches_balance(tenant)


def test_a_committed_spend_cannot_be_released_and_an_expired_hold_cannot_be_committed() -> None:
    _tenant, context, _ = setup_credits(slug="credits-states", allowance=40)

    with activate_tenant_context(context):
        spend_credits("assistant.rewrite_block", idempotency_key="block:done", at=NOW)
        with pytest.raises(CreditReservationConflict):
            release_credits("block:done")

        reserve_credits(
            "assistant.rewrite_block",
            idempotency_key="block:stale",
            at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )
        with pytest.raises(CreditReservationExpired):
            commit_credits("block:stale", at=NOW + timedelta(minutes=6))


def test_the_same_key_for_a_different_operation_is_a_conflict() -> None:
    _tenant, context, _ = setup_credits(slug="credits-conflict", allowance=40)

    with activate_tenant_context(context):
        reserve_credits("assistant.rewrite_block", idempotency_key="shared:key", at=NOW)
        with pytest.raises(CreditReservationConflict):
            reserve_credits("assistant.generate_draft", idempotency_key="shared:key", at=NOW)


def test_a_refund_compensates_and_never_rewrites_what_happened() -> None:
    tenant, context, _ = setup_credits(slug="credits-refund", allowance=30)

    with activate_tenant_context(context):
        spend_credits("assistant.generate_draft", idempotency_key="draft:bad", at=NOW)
        refund_credits("draft:bad", reason="Provider zwrócił błąd.", at=NOW)
        refund_credits("draft:bad", reason="Powtórka.", at=NOW)
        summary = credit_summary(at=NOW)

    assert summary.allowance_remaining == 30
    kinds = [
        entry.kind
        for entry in CreditLedgerEntry.all_objects.filter(organization=tenant).order_by(
            "occurred_at", "id"
        )
    ]
    assert kinds == [
        CreditLedgerKind.ALLOWANCE_GRANTED,
        CreditLedgerKind.CONSUMED,
        CreditLedgerKind.REFUNDED,
    ]
    assert_ledger_matches_balance(tenant)


def test_an_unmetered_operation_is_free_and_an_unknown_one_is_refused() -> None:
    """A typo must not turn into silent free usage."""
    tenant, context, _ = setup_credits(slug="credits-catalog", allowance=10)

    with activate_tenant_context(context):
        assert (
            reserve_credits("content_operations.proposal", idempotency_key="scr:1", at=NOW) is None
        )
        with pytest.raises(UnknownCreditOperation):
            reserve_credits("assistant.does_not_exist", idempotency_key="typo:1", at=NOW)
        summary = credit_summary(at=NOW)

    assert summary.available == 10
    assert not CreditReservation.all_objects.filter(organization=tenant).exists()


def test_activating_a_seeded_operation_starts_charging_for_it() -> None:
    _tenant, context, _ = setup_credits(slug="credits-switch", allowance=10)
    CreditOperation.objects.filter(key="content_operations.proposal").update(is_active=True)

    with activate_tenant_context(context):
        reservation = reserve_credits(
            "content_operations.proposal", idempotency_key="scr:2", at=NOW
        )

    assert reservation is not None
    assert reservation.cost == 1


def test_a_new_month_expires_the_allowance_but_not_what_was_bought() -> None:
    tenant, context, _ = setup_credits(slug="credits-rollover", allowance=100)
    next_month = NOW.replace(month=10, day=3)

    with activate_tenant_context(context):
        purchase = start_credit_purchase("credits-100", idempotency_key="buy:roll")
        complete_credit_purchase(
            organization_id=tenant.id,
            purchase_id=purchase.id,
            provider_reference="sim_ref_roll",
            at=NOW,
        )
        spend_credits("assistant.generate_draft", idempotency_key="draft:roll", at=NOW)
        before = credit_summary(at=NOW)
        assert before.allowance_remaining == 90
        assert before.purchased_remaining == 100

        after = credit_summary(at=next_month)

    assert after.allowance_remaining == 100
    assert after.purchased_remaining == 100
    expired = CreditLedgerEntry.all_objects.get(
        organization=tenant, kind=CreditLedgerKind.ALLOWANCE_EXPIRED
    )
    assert expired.amount == -90
    assert_ledger_matches_balance(tenant)


def test_a_hold_survives_the_month_it_was_taken_in() -> None:
    """Rollover expires what is free; a running operation keeps its credits."""
    tenant, context, _ = setup_credits(slug="credits-hold-rollover", allowance=100)
    next_month = NOW.replace(month=10, day=1)

    with activate_tenant_context(context):
        reserve_credits("assistant.generate_draft", idempotency_key="draft:cross", at=NOW)
        rolled = credit_summary(at=next_month)
        assert rolled.allowance_remaining == 110  # 10 still held + 100 granted
        commit_credits("draft:cross", at=next_month)
        after = credit_summary(at=next_month)

    assert after.allowance_remaining == 100
    assert_ledger_matches_balance(tenant)


def test_a_mid_month_upgrade_tops_the_allowance_up() -> None:
    tenant, context, _ = setup_credits(slug="credits-upgrade", allowance=50)

    with activate_tenant_context(context):
        credit_summary(at=NOW)
        EntitlementSnapshot.all_objects.filter(organization=tenant).update(
            quotas={"credits.monthly": 200}
        )
        upgraded = credit_summary(at=NOW + timedelta(days=1))

    assert upgraded.allowance_remaining == 200
    assert upgraded.allowance_granted == 200
    assert (
        CreditLedgerEntry.all_objects.filter(
            organization=tenant, kind=CreditLedgerKind.ALLOWANCE_GRANTED
        ).count()
        == 2
    )
    assert_ledger_matches_balance(tenant)


def test_read_only_access_stops_a_fresh_allowance_and_a_purchase() -> None:
    """Read-only means the data stays; it does not mean keep giving credits."""
    _tenant, context, _ = setup_credits(
        slug="credits-readonly", allowance=100, access_mode=AccessMode.READ_ONLY
    )

    with activate_tenant_context(context):
        summary = credit_summary(at=NOW)
        with pytest.raises(CreditsUnavailable):
            start_credit_purchase("credits-100", idempotency_key="buy:blocked")

    assert summary.available == 0


def test_a_purchase_credits_once_and_is_audited() -> None:
    tenant, context, _ = setup_credits(slug="credits-purchase", allowance=0)

    with activate_tenant_context(context):
        purchase = start_credit_purchase("credits-500", idempotency_key="buy:5")
        assert start_credit_purchase("credits-500", idempotency_key="buy:5").id == purchase.id
        with pytest.raises(CreditPurchaseConflict):
            start_credit_purchase("credits-100", idempotency_key="buy:5")

        complete_credit_purchase(
            organization_id=tenant.id,
            purchase_id=purchase.id,
            provider_reference="sim_ref_5",
            at=NOW,
        )
        complete_credit_purchase(
            organization_id=tenant.id,
            purchase_id=purchase.id,
            provider_reference="sim_ref_5",
            at=NOW,
        )
        summary = credit_summary(at=NOW)

    assert summary.purchased_remaining == 500
    assert CreditPurchase.all_objects.get(pk=purchase.pk).status == CreditPurchaseStatus.SUCCEEDED
    assert (
        CreditLedgerEntry.all_objects.filter(
            organization=tenant, kind=CreditLedgerKind.PURCHASED
        ).count()
        == 1
    )
    assert OrganizationAuditEntry.objects.filter(
        organization=tenant, action=OrganizationAuditAction.BILLING_CREDITS_PURCHASED
    ).exists()
    assert_ledger_matches_balance(tenant)


def test_an_operator_correction_needs_a_reason_an_operator_and_a_key() -> None:
    tenant, context, actor = setup_credits(slug="credits-operator", allowance=0)
    operator = User.objects.create_user(email="operator-credits@example.com")
    operator.is_staff = True
    operator.save(update_fields=["is_staff"])

    with activate_tenant_context(context):
        with pytest.raises(CreditsUnavailable):
            grant_operator_credits(
                organization_id=tenant.id,
                actor=actor,
                credits=100,
                reason="Nie jestem operatorem.",
                idempotency_key="fix:1",
                at=NOW,
            )
        with pytest.raises(ValueError):
            grant_operator_credits(
                organization_id=tenant.id,
                actor=operator,
                credits=100,
                reason="   ",
                idempotency_key="fix:1",
                at=NOW,
            )
        grant_operator_credits(
            organization_id=tenant.id,
            actor=operator,
            credits=100,
            reason="Rekompensata za awarię providera.",
            idempotency_key="fix:1",
            at=NOW,
        )
        grant_operator_credits(
            organization_id=tenant.id,
            actor=operator,
            credits=100,
            reason="Rekompensata za awarię providera.",
            idempotency_key="fix:1",
            at=NOW,
        )
        summary = credit_summary(at=NOW)

    assert summary.purchased_remaining == 100
    assert (
        OrganizationAuditEntry.objects.filter(
            organization=tenant, action=OrganizationAuditAction.BILLING_CREDITS_ADJUSTED
        ).count()
        == 1
    )
    assert_ledger_matches_balance(tenant)


def test_the_ledger_cannot_be_edited_or_deleted() -> None:
    tenant, context, _ = setup_credits(slug="credits-append-only", allowance=10)

    with activate_tenant_context(context):
        credit_summary(at=NOW)

    entry = CreditLedgerEntry.all_objects.get(organization=tenant)
    with pytest.raises(DatabaseError), transaction.atomic():
        CreditLedgerEntry.all_objects.filter(pk=entry.pk).update(amount=999)
    with pytest.raises(DatabaseError), transaction.atomic():
        CreditLedgerEntry.all_objects.filter(pk=entry.pk).delete()


def test_an_abandoned_hold_is_released_by_the_worker() -> None:
    tenant, context, _ = setup_credits(slug="credits-sweep", allowance=40)

    with activate_tenant_context(context):
        reserve_credits(
            "assistant.generate_draft",
            idempotency_key="draft:abandoned",
            at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )
        held = credit_summary(at=NOW)
        assert held.available == 30

    assert release_expired_credit_reservations(at=NOW + timedelta(minutes=6)) == 1

    with activate_tenant_context(context):
        after = credit_summary(at=NOW + timedelta(minutes=6))

    assert after.available == 40
    assert (
        CreditReservation.all_objects.get(
            organization=tenant, idempotency_key="draft:abandoned"
        ).state
        == CreditReservationState.RELEASED
    )


def test_the_allowance_sweep_reaches_organizations_nobody_looked_at() -> None:
    first, _first_context, _ = setup_credits(slug="credits-sweep-a", allowance=10)
    second, _second_context, _ = setup_credits(slug="credits-sweep-b", allowance=20)

    assert refresh_credit_allowances(at=NOW) >= 2

    for organization, expected in ((first, 10), (second, 20)):
        balance = CreditBalance.all_objects.get(organization=organization)
        assert balance.allowance_remaining == expected
        assert_ledger_matches_balance(organization)


def test_another_organizations_credits_are_invisible_under_the_app_role() -> None:
    mine, my_context, _ = setup_credits(slug="credits-rls-mine", allowance=10)
    theirs, their_context, _ = setup_credits(slug="credits-rls-theirs", allowance=10)
    for context in (my_context, their_context):
        with activate_tenant_context(context):
            credit_summary(at=NOW)

    role_name = f"credit_rls_{uuid.uuid7().hex}"
    quoted_role = connection.ops.quote_name(role_name)
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE ROLE {quoted_role} NOSUPERUSER NOBYPASSRLS NOLOGIN")
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {quoted_role}")
        cursor.execute(f"GRANT SELECT ON billing_creditledgerentry TO {quoted_role}")
        cursor.execute(f"SET LOCAL ROLE {quoted_role}")
        cursor.execute("SET LOCAL app.organization_id = %s", [str(mine.id)])
        cursor.execute("SELECT DISTINCT organization_id FROM billing_creditledgerentry")
        visible = {row[0] for row in cursor.fetchall()}
        assert visible == {mine.id}
        assert theirs.id not in visible
        cursor.execute("RESET ROLE")


def test_a_ledger_entry_cannot_name_another_organizations_reservation() -> None:
    mine, my_context, _ = setup_credits(slug="credits-guard-mine", allowance=40)
    _theirs, their_context, _ = setup_credits(slug="credits-guard-theirs", allowance=40)

    with activate_tenant_context(their_context):
        foreign = reserve_credits("assistant.rewrite_block", idempotency_key="theirs:hold", at=NOW)
    assert foreign is not None

    with pytest.raises(DatabaseError), transaction.atomic():
        set_local_organization_id(mine.id)
        CreditLedgerEntry.all_objects.create(
            organization_id=mine.id,
            kind=CreditLedgerKind.CONSUMED,
            bucket=CreditBucket.ALLOWANCE,
            amount=-1,
            balance_after=0,
            reservation=foreign,
        )
