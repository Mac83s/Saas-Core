"""How long the company keeps its customers' personal data (settings plan D1,
owner answer 37a; ADR-078).

`booking.retention.customers`: off — as it always was, a customer's data
stays until somebody anonymises them by hand — or 12, 24 or 36 months after
the customer's last visit. A customer is due when their last visit ended
longer ago than that and nothing is ahead; one who never had a visit counts
from the day their record was made.

Offered only where the deployment's profile says so (`customerRetention`): in
a product where the visit hangs on another record of the same person — a
farm's card — stripping the customer would leave them named there, and the
setting would promise more than happens.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Max, Q, QuerySet
from django.utils import timezone
from rest_framework.exceptions import NotFound

from saas_core.modules.core.organizations.api import (
    RETENTION_GRACE_DAYS,
    RETENTION_OFF,
    RETENTION_PERIODS,
    Effect,
    RetentionSweep,
    SettingGroup,
    SettingSpec,
    company_months,
    cutoff_for,
    excluded_ids,
    group_commands,
    held_back,
    months_of,
    register_command,
    register_retention_sweep,
    register_setting_group,
)
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.models import Organization, OrganizationSetting
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE
from saas_core.modules.shared.billing.api import FeatureOperation
from saas_core.modules.shared.billing.authorization import authorize_entitled
from saas_core.modules.shared.customers.api import (
    CUSTOMER_RETENTION_SWEEP,
    Customer,
    kept_after_strip,
    strip_customer,
)
from saas_core.modules.shared.notifications.retention_notice import announce_retention

from .models import Appointment
from .services import BOOKING_ENABLED, BOOKING_MANAGE

CUSTOMERS = "booking.retention.customers"
SWEEP = CUSTOMER_RETENTION_SWEEP
WHAT = {
    "pl": "dane osobowe klientów bez wizyty",
    "en": "personal data of customers with no visit",
}


def _months(count: int) -> dict[str, str]:
    return {"pl": f"Po {count} miesiącach", "en": f"After {count} months"}


def _past(organization_id: UUID, cutoff: datetime) -> QuerySet[Customer]:
    """The company's customers past the period at `cutoff`: not anonymised
    yet, their latest visit — whatever became of it — ended before the cutoff
    (so nothing is under way or ahead), or, with no visit at all, their record
    is older than the cutoff."""
    return (
        Customer.all_objects.filter(organization_id=organization_id, anonymized_at__isnull=True)
        .annotate(last_visit_end=Max("appointments__ends_at"))
        .filter(
            Q(last_visit_end__lt=cutoff) | Q(last_visit_end__isnull=True, created_at__lt=cutoff)
        )
    )


def customers_due(organization_id: UUID, cutoff: datetime) -> QuerySet[Customer]:
    """The customers whose data a run would remove at `cutoff`: past the
    period, and never one another module still needs
    (`register_retention_exclusion`) — the buyer of a sales record inside its
    statutory period stays until that period ends."""
    return _past(organization_id, cutoff).exclude(id__in=excluded_ids(SWEEP, organization_id))


def customers_held(organization_id: UUID, cutoff: datetime) -> list[tuple[Mapping[str, str], int]]:
    """How many customers past the period another module holds back, and why
    — for the preview: the company is told what its choice will not remove."""
    past = set(_past(organization_id, cutoff).values_list("id", flat=True))
    return held_back(SWEEP, organization_id, past)


def erase_customers(organization_id: UUID, cutoff: datetime, limit: int) -> int:
    """Strips up to `limit` due customers, inside the company's tenant and the
    run's transaction. The rows are locked in id order, and whether a visit
    ends after the cutoff is asked again under locks: a booking committed
    between finding the customer and locking them keeps them, and so does a
    visit somebody moves ahead meanwhile. Moving a visit locks the visit, not
    its customer, so the customers' visits are locked here too — all of them,
    and the date read from the locked row: a move in flight makes the run wait
    and is then seen, one that starts later waits for the run and finds the
    customer stripped. The order is customer, then visit; a move takes the
    visit alone, so nothing can wait in a circle. What another module still
    needs is asked for last, under the same locks (`excluded_ids` with
    `among`)."""
    found = list(
        customers_due(organization_id, cutoff).order_by("id").values_list("id", flat=True)[:limit]
    )
    if not found:
        return 0
    locked = list(
        Customer.all_objects.select_for_update(no_key=True)
        .filter(organization_id=organization_id, id__in=found, anonymized_at__isnull=True)
        .order_by("id")
    )
    # No `ends_at` in the filter: a row that does not match yet would be
    # neither locked nor waited for. NO KEY, as for the customer — rows that
    # only point at a visit do not queue behind the run.
    visits = (
        Appointment.all_objects.select_for_update(no_key=True)
        .filter(
            organization_id=organization_id,
            customer_id__in=[customer.id for customer in locked],
        )
        .order_by("id")
        .values_list("customer_id", "ends_at")
    )
    still_visiting = {customer_id for customer_id, ends_at in visits if ends_at >= cutoff}
    # Other modules are asked again, now that the customers are locked: each
    # locks what its own answer depends on, so a payment marked between
    # finding the customer and locking them keeps them, like a new visit.
    still_needed = excluded_ids(SWEEP, organization_id, among=[customer.id for customer in locked])
    stripped = 0
    for customer in locked:
        if customer.id in still_visiting or customer.id in still_needed:
            continue
        strip_customer(customer)
        stripped += 1
    return stripped


def anonymization_preview(customer_id: UUID) -> dict[str, Any]:
    """What taking this customer out by hand would leave, read before anybody
    decides (`anonymize_customer` cannot be undone): the customer's row, the
    visits' notes and addresses, the links and the stored mails go; what a
    module must keep for a time — the buyer on a paid order, until its
    statutory period ends — is listed with the day and the reason. Asked of
    the same registry the strip itself runs (`customers.kept_after_strip`)."""
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED, operation=FeatureOperation.READ)
    customer = Customer.all_objects.filter(
        organization_id=context.organization_id, pk=customer_id
    ).first()
    if customer is None:
        raise NotFound("Klient nie istnieje.")
    return {
        "id": customer.id,
        "anonymized_at": customer.anonymized_at,
        "kept": [asdict(item) for item in kept_after_strip(customer)],
    }


def starts_on(organization_id: UUID) -> date:
    """The first day a removal switched on now could happen, as the company
    reads its calendar."""
    zone = Organization.objects.values_list("timezone", flat=True).get(pk=organization_id)
    moment = timezone.now() + timedelta(days=RETENTION_GRACE_DAYS)
    return moment.astimezone(ZoneInfo(zone)).date()


def _widens(before: Mapping[str, Any], after: Mapping[str, Any]) -> int | None:
    """The period a change switches on or makes sooner; None for any other."""
    new, old = months_of(after["customers"]), months_of(before["customers"])
    return new if new is not None and (old is None or new < old) else None


def _effects(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[Effect, ...]:
    months = months_of(after["customers"])
    if months is None or after["customers"] == before["customers"]:
        return ()
    organization_id = require_tenant_context().organization_id
    cutoff = cutoff_for(months)
    count = customers_due(organization_id, cutoff).count()
    day = starts_on(organization_id).isoformat()
    # Who stays although their time has come, and why — said before the save.
    held = customers_held(organization_id, cutoff)
    stays = {
        locale: "".join(
            f" {lead}: {number} — {why.get(locale) or why.get('en', '')}."
            for why, number in held
            if why
        )
        for locale, lead in (
            ("pl", "Klienci po terminie, którzy na razie zostają"),
            ("en", "Customers past their time who stay for now"),
        )
    }
    return (
        Effect(
            kind="erasure_scheduled",
            resource="booking.customer",
            resource_id="",
            summary={
                "pl": f"Klienci bez wizyty od ponad {months} miesięcy, których dotyczy teraz: "
                f"{count}. Ich dane osobowe zostaną usunięte bez możliwości przywrócenia, "
                f"najwcześniej {day}; dane kolejnych klientów — gdy minie ich termin. "
                "Właściciele firmy dostaną o tym e-mail." + stays["pl"],
                "en": f"Customers with no visit for over {months} months, affected now: "
                f"{count}. Their personal data will be removed for good, on {day} at the "
                "earliest; further customers' data when their time comes. The company's "
                "owners get an e-mail about it." + stays["en"],
            },
        ),
    )


def _announce(before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    months = _widens(before, after)
    if months is None:
        return
    organization_id = require_tenant_context().organization_id
    version = (
        OrganizationSetting.objects.filter(organization_id=organization_id, key=CUSTOMERS)
        .values_list("version", flat=True)
        .first()
    )
    announce_retention(
        key=CUSTOMERS,
        what=WHAT,
        months=months,
        count=customers_due(organization_id, cutoff_for(months)).count(),
        starts_on=starts_on(organization_id),
        version=int(version or 0),
    )


RETENTION = SettingGroup(
    key="booking.retention",
    module="shared.booking",
    title={"pl": "Dane klientów", "en": "Customers' data"},
    description={
        "pl": "Po jakim czasie od ostatniej wizyty firma usuwa dane osobowe klienta. Usunięcia "
        "nie da się cofnąć. Wizyty zostają w kalendarzu i statystykach, bez danych osoby.",
        "en": "How long after a customer's last visit the company removes their personal "
        "data. A removal cannot be undone. The visits stay in the calendar and the "
        "statistics, without the person's data.",
    },
    permission=SETTINGS_MANAGE,
    area="privacy",
    # Turning it on removes people's data for good: never without a person.
    risk="irreversible",
    commands=("booking.settings_retention.read@1", "booking.settings_retention.update@1"),
    effects=_effects,
    on_changed=_announce,
    settings=(
        SettingSpec(
            key=CUSTOMERS,
            type="enum",
            default=RETENTION_OFF,
            scopes=("organization",),
            # The company's own decision: no profile switches a removal on.
            product_default=False,
            values=(
                (RETENTION_OFF, {"pl": "Nie usuwaj", "en": "Do not remove"}),
                *((str(count), _months(count)) for count in RETENTION_PERIODS),
            ),
            label={
                "pl": "Usuwaj dane klienta po ostatniej wizycie",
                "en": "Remove a customer's data after their last visit",
            },
            help={
                "pl": "Dotyczy klienta, którego ostatnia wizyta skończyła się dawniej i który "
                "nie ma żadnej wizyty przed sobą. Usuwane: imię i nazwisko, e-mail, telefon, "
                "uwagi klienta do wizyt, adres wizyty u klienta i adres w zapisie wysłanych "
                "wiadomości; link klienta do zarządzania wizytą przestaje działać. Zostaje: "
                "sama wizyta — termin, usługa, osoba z firmy, miejscowość — oraz e-maile, "
                "które klient już dostał. Klient, którego dane firma musi jeszcze przechowywać "
                "— kupujący z zamówienia z wpłatą — zostaje do końca tego okresu; podgląd "
                "przed zapisem mówi, ilu takich jest. Po włączeniu nic nie znika przez "
                f"{RETENTION_GRACE_DAYS} dni.",
                "en": "Applies to a customer whose last visit ended longer ago and who has no "
                "visit ahead. Removed: name, e-mail, phone, the customer's notes on visits, "
                "the address of a visit at the customer's and the address in the record of "
                "messages sent; the customer's link for managing a visit stops working. Kept: "
                "the visit itself — its time, service, the company's person, the town — and "
                "the e-mails the customer already received. A customer whose data the "
                "company must still keep — the buyer of an order that was paid for — stays "
                "until that period ends; the preview before saving says how many there are. "
                f"After switching it on, nothing goes for {RETENTION_GRACE_DAYS} days.",
            },
            model_description="After how many months from a customer's last visit their "
            "personal data is removed for good (name, e-mail, phone, their notes, the street "
            "of a visit at theirs, the copies in stored messages); `off` removes nothing. "
            "Only a customer with no visit ahead is affected; the visits stay without the "
            "person's data. A customer who bought something that was paid for stays until "
            "the sales record's statutory period ends; the preview counts them. "
            f"Nothing is removed for {RETENTION_GRACE_DAYS} days after the "
            "value changes, and the owners are told by e-mail. Irreversible: a person in "
            "the company must decide, never the assistant on its own.",
        ),
    ),
)


def register_retention() -> None:
    """Only where the profile offers it (`features.customerRetention`)."""
    if not settings.CUSTOMER_RETENTION_OFFERED:
        return
    register_setting_group(RETENTION)
    for command in group_commands(RETENTION):
        register_command(command)
    register_retention_sweep(
        RetentionSweep(
            key=SWEEP,
            rule=company_months(CUSTOMERS),
            due=lambda organization_id, cutoff: customers_due(organization_id, cutoff).count(),
            erase=erase_customers,
        )
    )
