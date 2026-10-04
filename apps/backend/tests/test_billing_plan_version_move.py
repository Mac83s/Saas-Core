"""An operator brings companies to the current version of their plan (owner
decisions of 2026-10-04): on purpose and never by itself, after a dry run that
names who would move and what each gains or loses; at the same price in one
run, at another price one named company behind the operator's code; a
subscription kept at Stripe is refused and left exactly as it was."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from typing import Any

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from saas_core.modules.core.identity.mfa import current_totp_code
from saas_core.modules.core.identity.models import OperatorGrant, User
from saas_core.modules.core.identity.operators import OperatorLevelRequired
from saas_core.modules.core.identity.step_up import StepUpRequired
from saas_core.modules.core.organizations.models import (
    Organization,
    OrganizationAuditEntry,
    OrganizationStatus,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    BillingSubscription,
    EntitlementSnapshot,
    Feature,
    Plan,
    PlanVersion,
    StripePriceMapping,
    StripeSubscriptionStatus,
    SubscriptionState,
)
from saas_core.modules.shared.billing.plan_versions import (
    PLAN_VERSION_MOVED,
    PlanMoveRefused,
    apply_plan_move,
    pending_plan_moves,
    plan_move,
)
from saas_core.modules.shared.billing.simulated_clock import advance_simulated_billing
from saas_core.modules.shared.billing.snapshots import update_entitlement_snapshot
from test_billing_api import billing_client
from test_platform_workspace import confirm_mfa, operator

pytestmark = pytest.mark.django_db

COMMAND = "plan_version_move"
REASON = "Nowa wersja planu dla firm testowych"


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    """Wrong authenticator codes are counted in the cache."""
    cache.clear()


def _company(slug: str) -> Organization:
    return Organization.objects.create(name=slug, slug=slug, status=OrganizationStatus.ACTIVE)


def _current(plan_key: str) -> PlanVersion:
    version = Plan.objects.select_related("current_version").get(key=plan_key).current_version
    assert version is not None
    return version


def _price(version: PlanVersion, *, provider: str = "stripe") -> StripePriceMapping:
    return StripePriceMapping.objects.create(
        plan_version=version,
        stripe_product_id=f"prod_{version.plan.key}",
        stripe_price_id=f"{provider}_price_{version.plan.key}_v{version.version}",
        provider=provider,
        livemode=False,
    )


def _granted(organization: Organization, mapping: StripePriceMapping) -> None:
    """A plan given by hand: the snapshot of a paid plan, no subscription."""
    update_entitlement_snapshot(
        organization,
        mapping,
        state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        effective_until=None,
    )


def _subscribed(organization: Organization, mapping: StripePriceMapping) -> BillingSubscription:
    started = timezone.now() - timedelta(days=10)
    subscription = BillingSubscription.all_objects.create(
        organization=organization,
        price_mapping=mapping,
        stripe_subscription_id=f"sub_{organization.slug}",
        state=SubscriptionState.ACTIVE,
        provider_status=StripeSubscriptionStatus.ACTIVE,
        current_period_start=started,
        current_period_end=started + timedelta(days=30),
    )
    update_entitlement_snapshot(
        organization,
        mapping,
        state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        effective_until=subscription.current_period_end,
    )
    return subscription


def _catalogue_moves_on(
    plan_key: str,
    *,
    unit_amount_minor: int | None = None,
    drop_feature: str | None = None,
    quotas: dict[str, int] | None = None,
) -> PlanVersion:
    """A newer version becomes the plan's offer — by default at the same price,
    with one more feature and a higher limit of sites. Returns it."""
    Feature.objects.get_or_create(
        key="newer.feature", defaults={"name": "Nowsza funkcja", "module": "shared.billing"}
    )
    plan = Plan.objects.select_related("current_version").get(key=plan_key)
    older = plan.current_version
    assert older is not None
    plan.current_version = PlanVersion.objects.create(
        plan=plan,
        version=older.version + 1,
        currency=older.currency,
        billing_interval=older.billing_interval,
        unit_amount_minor=(
            older.unit_amount_minor if unit_amount_minor is None else unit_amount_minor
        ),
        feature_keys=[*(key for key in older.feature_keys if key != drop_feature), "newer.feature"],
        quotas={**older.quotas, "sites.max": 99} if quotas is None else quotas,
        trial_days=older.trial_days,
    )
    plan.save(update_fields=["current_version", "updated_at"])
    return plan.current_version


def _operator(*, level: int = 2, email: str = "operator@example.test") -> tuple[User, str]:
    person = operator(email=email)
    secret = confirm_mfa(person)
    if level == 2:
        OperatorGrant.objects.create(user=person, reason="test")
    return person, secret


def _next_code(secret: str) -> str:
    """A code the enrolment has not used yet."""
    return current_totp_code(secret, at=timezone.now().timestamp() + 30)


def _run(**options: Any) -> str:
    out = StringIO()
    call_command(COMMAND, stdout=out, **options)
    return out.getvalue()


def _snapshot(organization: Organization) -> EntitlementSnapshot:
    return EntitlementSnapshot.all_objects.select_related("plan_version").get(
        organization=organization
    )


def _history(organization: Organization) -> list[OrganizationAuditEntry]:
    return list(
        OrganizationAuditEntry.objects.filter(organization=organization, action=PLAN_VERSION_MOVED)
    )


def test_the_dry_run_names_who_would_move_and_what_each_gains_and_writes_nothing() -> None:
    company = _company("move-preview")
    given = _current("pro")
    _granted(company, _price(given))
    _catalogue_moves_on("pro")
    before = _snapshot(company).version

    out = _run()

    assert f"move-preview ({company.id})" in out
    assert f"plan pro: wersja {given.version} → {given.version + 1}, plan nadany bez" in out
    assert "cena: bez zmian (299,00 PLN netto / miesiąc)" in out
    assert "zyskuje: Nowsza funkcja (newer.feature)" in out
    assert f"sites.max): {given.quotas['sites.max']} → 99" in out
    assert "→ zostałaby przeniesiona" in out
    assert "PODGLĄD — niczego nie zapisano. Do przeniesienia: 1, bez zmian: 0." in out
    snapshot = _snapshot(company)
    assert (snapshot.plan_version, snapshot.version) == (given, before)
    assert _history(company) == []


@override_settings(BILLING_PLAN_KEYS=("profile", "starter", "pro"))
def test_a_granted_plan_moves_with_a_history_entry_and_a_second_run_changes_nothing() -> None:
    client, company = billing_client(role_key="owner", slug="move-granted")
    given = _current("pro")
    _granted(company, _price(given))
    current = _catalogue_moves_on("pro")
    person, _secret = _operator()

    out = _run(apply=True, operator=person.email, reason=REASON)

    assert "→ przeniesiona" in out
    assert "Przeniesione: 1, bez zmian: 0." in out
    snapshot = _snapshot(company)
    assert snapshot.plan_version == current
    assert snapshot.features["newer.feature"] is True
    assert snapshot.quotas["sites.max"] == 99
    # Whether the plan is in force is not the move's to change.
    assert (snapshot.subscription_state, snapshot.access_mode, snapshot.effective_until) == (
        SubscriptionState.ACTIVE,
        AccessMode.FULL,
        None,
    )
    assert snapshot.sources["newer.feature"] == {"kind": "plan", "ref": f"pro:v{current.version}"}
    (entry,) = _history(company)
    assert entry.actor_user == person
    assert entry.target_id == current.id
    assert entry.metadata == {
        "plan": "pro",
        "from_version": given.version,
        "to_version": current.version,
        "payment": "granted",
        "price_from": {"unit_amount_minor": 29_900, "currency": "PLN", "billing_interval": "month"},
        "price_to": {"unit_amount_minor": 29_900, "currency": "PLN", "billing_interval": "month"},
        "gained_features": ["newer.feature"],
        "lost_features": [],
        "raised_limits": {"sites.max": [given.quotas["sites.max"], 99]},
        "lowered_limits": {},
        "reason": REASON,
    }
    # The plan card (package J): the company's terms are the catalogue's again,
    # so there is no „nowsze warunki” line to show.
    card = next(
        plan for plan in client.get("/api/v1/billing/overview/").data["plans"] if plan["is_current"]
    )
    assert (card["key"], card["own_terms"]["version"]) == ("pro", card["version"])

    again = _run(apply=True, operator=person.email, reason=REASON)

    assert "Żadna firma nie jest na starszej wersji swojego planu." in again
    assert "Przeniesione: 0, bez zmian: 0." in again
    assert "Ta firma nie ma planu albo jest już na jego bieżącej wersji." in _run(
        organization=str(company.id)
    )
    assert _snapshot(company).version == snapshot.version
    assert len(_history(company)) == 1


def test_a_run_never_touches_a_company_whose_version_differs_in_price() -> None:
    company = _company("move-other-price")
    given = _current("starter")
    _granted(company, _price(given))
    _catalogue_moves_on("starter", unit_amount_minor=given.unit_amount_minor + 5_000)
    person, _secret = _operator()
    before = _snapshot(company).version

    out = _run(apply=True, operator=person.email, reason=REASON)

    assert "cena: 149,00 PLN netto / miesiąc → 199,00 PLN netto / miesiąc" in out
    assert "→ zostaje: Bieżąca wersja planu ma inną cenę." in out
    assert "Przeniesione: 0, bez zmian: 1." in out
    snapshot = _snapshot(company)
    assert (snapshot.plan_version, snapshot.version) == (given, before)
    assert _history(company) == []
    # The consent to another price is for one named company only.
    with pytest.raises(CommandError, match="tylko z --organization"):
        _run(apply=True, operator=person.email, reason=REASON, accept_price_change=True)
    assert _snapshot(company).plan_version == given


def test_what_the_newer_version_takes_away_is_listed_and_needs_the_flag() -> None:
    company = _company("move-losses")
    given = _current("pro")
    dropped = given.feature_keys[0]
    lowered = {**given.quotas, "sites.max": 0}
    removed_limit = next(key for key in lowered if key != "sites.max")
    del lowered[removed_limit]
    _granted(company, _price(given))
    current = _catalogue_moves_on("pro", drop_feature=dropped, quotas=lowered)
    person, _secret = _operator()

    preview = _run()

    assert f"({dropped})" in preview.split("TRACI: ")[1].splitlines()[0]
    lower_line = preview.split("NIŻSZE LIMITY: ")[1].splitlines()[0]
    assert f"sites.max): {given.quotas['sites.max']} → 0" in lower_line
    assert f"{removed_limit}): {given.quotas[removed_limit]} → brak" in lower_line
    assert "→ zostałaby: Bieżąca wersja planu coś firmie odbiera." in preview
    assert "Do przeniesienia: 0, bez zmian: 1." in preview

    refused = _run(apply=True, operator=person.email, reason=REASON)

    assert "Dodaj --accept-losses" in refused
    assert _snapshot(company).plan_version == given
    assert _history(company) == []

    accepted = _run(apply=True, operator=person.email, reason=REASON, accept_losses=True)

    assert "→ przeniesiona" in accepted
    snapshot = _snapshot(company)
    assert snapshot.plan_version == current
    assert dropped not in snapshot.features
    assert removed_limit not in snapshot.quotas
    (entry,) = _history(company)
    assert entry.metadata["lost_features"] == [dropped]
    assert entry.metadata["lowered_limits"] == {
        "sites.max": [given.quotas["sites.max"], 0],
        removed_limit: [given.quotas[removed_limit], None],
    }


def test_a_subscription_at_stripe_is_refused_and_left_as_it_was() -> None:
    """Its version is its price at the provider, and nothing here changes a
    running subscription's price: the next webhook would undo a local move."""
    company = _company("move-stripe")
    bought = _current("starter")
    subscription = _subscribed(company, _price(bought))
    _price(_catalogue_moves_on("starter"))
    person, _secret = _operator()
    before = _snapshot(company).version

    preview = _run()
    out = _run(apply=True, operator=person.email, reason=REASON, accept_losses=True)

    for text in (preview, out):
        assert "subskrypcja w Stripe" in text
        assert "moduł rozliczeń nie zmienia ceny trwającej subskrypcji" in text
    assert "Przeniesione: 0, bez zmian: 1." in out
    subscription.refresh_from_db()
    assert subscription.price_mapping.plan_version == bought
    assert subscription.version == 1
    snapshot = _snapshot(company)
    assert (snapshot.plan_version, snapshot.version) == (bought, before)
    assert _history(company) == []
    # Naming the company and accepting everything changes nothing either.
    with pytest.raises(CommandError, match="Firmy nie przeniesiono"):
        _run(
            organization=str(company.id),
            apply=True,
            operator=person.email,
            reason=REASON,
            accept_losses=True,
            accept_price_change=True,
        )
    with pytest.raises(PlanMoveRefused) as refusal:
        apply_plan_move(
            company.id,
            operator=person,
            reason=REASON,
            accept_losses=True,
            accept_price_change=True,
        )
    assert refusal.value.get_codes() == "billing_plan_move_stripe_subscription"
    assert _snapshot(company).plan_version == bought


def test_a_simulated_subscription_moves_with_its_price_and_keeps_the_version_at_renewal() -> None:
    company = _company("move-simulated")
    bought = _current("starter")
    subscription = _subscribed(company, _price(bought, provider="simulated"))
    current = _catalogue_moves_on("starter")
    person, _secret = _operator()

    without_price = _run(apply=True, operator=person.email, reason=REASON)

    assert "nie ma aktywnej ceny w symulatorze płatności" in without_price
    assert "configure_simulated_prices" in without_price
    assert _snapshot(company).plan_version == bought

    price = _price(current, provider="simulated")
    out = _run(apply=True, operator=person.email, reason=REASON)

    assert "subskrypcja w symulatorze płatności" in out
    assert "→ przeniesiona" in out
    subscription.refresh_from_db()
    assert (subscription.price_mapping, subscription.version) == (price, 2)
    assert subscription.state == SubscriptionState.ACTIVE
    snapshot = _snapshot(company)
    assert snapshot.plan_version == current
    assert snapshot.effective_until == subscription.current_period_end
    assert snapshot.sources["newer.feature"]["stripe_price_id"] == price.stripe_price_id
    (entry,) = _history(company)
    assert entry.metadata["payment"] == "simulated"
    # The simulator's clock rolls the period from the subscription's price, so
    # the next period is on the version the company was moved to.
    assert subscription.current_period_end is not None
    with override_settings(BILLING_PROVIDER="simulated"):
        assert advance_simulated_billing(at=subscription.current_period_end + timedelta(days=1))
    assert _snapshot(company).plan_version == current


def test_another_price_moves_one_named_company_behind_the_operators_code() -> None:
    company = _company("move-named")
    bystander = _company("move-bystander")
    given = _current("starter")
    mapping = _price(given)
    _granted(company, mapping)
    _granted(bystander, mapping)
    current = _catalogue_moves_on("starter", unit_amount_minor=given.unit_amount_minor + 5_000)
    person, secret = _operator()
    named = {"organization": str(company.id), "operator": person.email, "reason": REASON}

    preview = _run(organization=str(company.id))

    assert "cena: 149,00 PLN netto / miesiąc → 199,00 PLN netto / miesiąc" in preview
    assert "Firma nie płaci za ten plan (nadany bez płatności)" in preview
    assert "--organization <id> --accept-price-change --code" in preview
    assert "move-bystander" not in preview
    with pytest.raises(CommandError, match="Firmy nie przeniesiono"):
        _run(apply=True, **named)
    with pytest.raises(CommandError, match="Zmiana ceny wymaga --code"):
        _run(apply=True, accept_price_change=True, **named)
    with pytest.raises(CommandError, match="Kod uwierzytelniający jest nieprawidłowy"):
        _run(apply=True, accept_price_change=True, code="000000", **named)
    assert _snapshot(company).plan_version == given
    assert _history(company) == []

    out = _run(apply=True, accept_price_change=True, code=_next_code(secret), **named)

    assert "→ przeniesiona" in out
    assert _snapshot(company).plan_version == current
    (entry,) = _history(company)
    assert entry.metadata["price_from"]["unit_amount_minor"] == given.unit_amount_minor
    assert entry.metadata["price_to"]["unit_amount_minor"] == given.unit_amount_minor + 5_000
    assert _snapshot(bystander).plan_version == given
    assert _history(bystander) == []


def test_the_service_itself_asks_for_level_2_a_reason_and_a_step_up_at_another_price() -> None:
    company = _company("move-gate")
    given = _current("starter")
    _granted(company, _price(given))
    _catalogue_moves_on("starter", unit_amount_minor=given.unit_amount_minor + 5_000)
    level_one, _ = _operator(level=1, email="level-one@example.test")
    level_two, _ = _operator()

    with pytest.raises(OperatorLevelRequired):
        apply_plan_move(company.id, operator=level_one, reason=REASON, accept_price_change=True)
    with pytest.raises(StepUpRequired):
        apply_plan_move(company.id, operator=level_two, reason=REASON, accept_price_change=True)
    with pytest.raises(CommandError, match="nie ma poziomu 2"):
        _run(apply=True, operator=level_one.email, reason=REASON)
    with pytest.raises(CommandError, match="Podaj --operator"):
        _run(apply=True, reason=REASON)
    with pytest.raises(CommandError, match="Podaj --reason"):
        _run(apply=True, operator=level_two.email)
    assert _snapshot(company).plan_version == given
    assert _history(company) == []


def test_a_plan_that_is_not_in_force_and_a_company_without_a_plan_stay_out() -> None:
    ended = _company("move-ended")
    given = _current("pro")
    update_entitlement_snapshot(
        ended,
        _price(given),
        state=SubscriptionState.CANCELED,
        access_mode=AccessMode.BLOCKED,
        effective_until=None,
    )
    without_plan = _company("move-no-plan")
    _catalogue_moves_on("pro")
    person, _secret = _operator()

    out = _run(apply=True, operator=person.email, reason=REASON)

    assert "Plan firmy nie jest teraz w mocy" in out
    assert "move-no-plan" not in out
    assert _snapshot(ended).plan_version == given
    assert plan_move(without_plan.id) is None
    assert [move.organization_id for move in pending_plan_moves(plan_key="pro")] == [ended.id]
    assert pending_plan_moves(plan_key="starter") == []
    with pytest.raises(CommandError, match="Nie ma planu o kluczu por"):
        _run(plan="por")


def _assert_tenant_set_first(captured: CaptureQueriesContext, company: Organization) -> None:
    sql = [query["sql"] for query in captured.captured_queries]
    tenant = next(i for i, statement in enumerate(sql) if "app.organization_id" in statement)
    assert str(company.id) in sql[tenant]
    for table in (
        '"organizations_organization"',
        '"billing_entitlementsnapshot"',
        '"billing_billingsubscription"',
    ):
        first = next(i for i, statement in enumerate(sql) if table in statement)
        assert tenant < first, f"{table} przed SET LOCAL"


def test_the_tenant_is_set_before_the_companys_rows_are_read() -> None:
    """Under the application's role a read before SET LOCAL answers with no
    rows — also of the company itself. The suite's database does not show it:
    the first run on a stack said „Nie ma firmy o id …” about a company the dry
    run had just listed, because the command looked the id up before setting
    the tenant."""
    company = _company("move-order")
    _granted(company, _price(_current("pro")))
    _catalogue_moves_on("pro")
    person, _secret = _operator()

    with CaptureQueriesContext(connection) as named:
        assert "→ zostałaby przeniesiona" in _run(organization=str(company.id))
    _assert_tenant_set_first(named, company)

    with CaptureQueriesContext(connection) as applied:
        assert apply_plan_move(company.id, operator=person, reason=REASON) is not None
    _assert_tenant_set_first(applied, company)
    sql = [query["sql"] for query in applied.captured_queries]
    tenant = next(i for i, statement in enumerate(sql) if "app.organization_id" in statement)
    for table in ('"billing_entitlementgrant"', '"organizations_organizationauditentry"'):
        assert tenant < next(i for i, statement in enumerate(sql) if table in statement)
