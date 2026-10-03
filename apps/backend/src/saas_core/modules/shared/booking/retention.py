"""How long the company keeps its customers' personal data (settings plan D1,
owner answer 37a; ADR-078).

`booking.retention.customers`: off — as it always was, a customer's data
stays until somebody anonymises them by hand — or 12, 24 or 36 months after
the customer's last visit. A customer is due when their last visit ended
longer ago than that and nothing is ahead; one who never had a visit counts
from the day their record was made.

This module declares the setting and finds who is due. It removes nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import Max, Q, QuerySet

from saas_core.modules.core.organizations.api import (
    RETENTION_OFF,
    RETENTION_PERIODS,
    Effect,
    RetentionSweep,
    SettingGroup,
    SettingSpec,
    cutoff_for,
    group_commands,
    months_of,
    register_command,
    register_retention_sweep,
    register_setting_group,
)
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE

from .models import Customer

CUSTOMERS = "booking.retention.customers"


def _months(count: int) -> dict[str, str]:
    return {"pl": f"Po {count} miesiącach", "en": f"After {count} months"}


def customers_due(organization_id: UUID, cutoff: datetime) -> QuerySet[Customer]:
    """The company's customers whose data a run would remove at `cutoff`: not
    anonymised yet, their latest visit — whatever became of it — ended before
    the cutoff (so nothing is under way or ahead), or, with no visit at all,
    their record is older than the cutoff."""
    return (
        Customer.all_objects.filter(organization_id=organization_id, anonymized_at__isnull=True)
        .annotate(last_visit_end=Max("appointments__ends_at"))
        .filter(
            Q(last_visit_end__lt=cutoff) | Q(last_visit_end__isnull=True, created_at__lt=cutoff)
        )
    )


def _effects(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[Effect, ...]:
    months = months_of(after["customers"])
    if months is None or after["customers"] == before["customers"]:
        return ()
    count = customers_due(require_tenant_context().organization_id, cutoff_for(months)).count()
    return (
        Effect(
            kind="erasure_scheduled",
            resource="booking.customer",
            resource_id="",
            summary={
                "pl": f"Klienci bez wizyty od ponad {months} miesięcy, których dotyczy teraz: "
                f"{count}. Ich dane osobowe zostaną usunięte bez możliwości przywrócenia; "
                "dane kolejnych klientów — gdy minie ich termin.",
                "en": f"Customers with no visit for over {months} months, affected now: "
                f"{count}. Their personal data will be removed for good; further customers' "
                "data when their time comes.",
            },
        ),
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
    settings=(
        SettingSpec(
            key=CUSTOMERS,
            type="enum",
            default=RETENTION_OFF,
            scopes=("organization",),
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
                "wiadomości. Zostaje: sama wizyta — termin, usługa, osoba z firmy, "
                "miejscowość — oraz e-maile, które klient już dostał.",
                "en": "Applies to a customer whose last visit ended longer ago and who has no "
                "visit ahead. Removed: name, e-mail, phone, the customer's notes on visits, "
                "the address of a visit at the customer's and the address in the record of "
                "messages sent. Kept: the visit itself — its time, service, the company's "
                "person, the town — and the e-mails the customer already received.",
            },
            model_description="After how many months from a customer's last visit their "
            "personal data is removed for good (name, e-mail, phone, their notes, the street "
            "of a visit at theirs); `off` removes nothing. Only a customer with no visit "
            "ahead is affected; the visits stay without the person's data. Irreversible: a "
            "person in the company must decide, never the assistant on its own.",
        ),
    ),
    effects=_effects,
)


def register_retention() -> None:
    register_setting_group(RETENTION)
    for command in group_commands(RETENTION):
        register_command(command)
    register_retention_sweep(
        RetentionSweep(
            key="booking.customers",
            setting=CUSTOMERS,
            due=lambda organization_id, cutoff: customers_due(organization_id, cutoff).count(),
        )
    )
