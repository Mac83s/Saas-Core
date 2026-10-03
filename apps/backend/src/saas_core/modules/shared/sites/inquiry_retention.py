"""How long the company keeps the enquiries from its site (settings plan D2,
owner answer 37a; ADR-078).

`sites.retention.inquiries`: off — as it always was, an enquiry stays until
the company is erased — or 12, 24 or 36 months after it arrived. An enquiry
is the personal data of somebody who is not the company's customer yet: a
name, an e-mail or a phone, and what they wrote.

This module declares the setting and finds what is due. It removes nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import QuerySet

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

from .models import SiteInquiry

INQUIRIES = "sites.retention.inquiries"


def inquiries_due(organization_id: UUID, cutoff: datetime) -> QuerySet[SiteInquiry]:
    """The company's enquiries a run would remove at `cutoff`: those that
    arrived before it, read or not."""
    return SiteInquiry.all_objects.filter(organization_id=organization_id, created_at__lt=cutoff)


def _effects(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[Effect, ...]:
    months = months_of(after["inquiries"])
    if months is None or after["inquiries"] == before["inquiries"]:
        return ()
    count = inquiries_due(require_tenant_context().organization_id, cutoff_for(months)).count()
    return (
        Effect(
            kind="erasure_scheduled",
            resource="sites.inquiry",
            resource_id="",
            summary={
                "pl": f"Zapytania starsze niż {months} miesięcy, których dotyczy teraz: {count}. "
                "Dane osoby i treść zostaną z nich usunięte bez możliwości przywrócenia; z "
                "kolejnych — gdy minie ich termin. E-maile z zapytaniami, które już trafiły "
                "na skrzynki firmy, zostają tam.",
                "en": f"Enquiries older than {months} months, affected now: {count}. The "
                "person's data and the text will be removed from them for good; from further "
                "ones when their time comes. The e-mails with enquiries already delivered to "
                "the company's mailboxes stay there.",
            },
        ),
    )


def _months(count: int) -> dict[str, str]:
    return {"pl": f"Po {count} miesiącach", "en": f"After {count} months"}


RETENTION = SettingGroup(
    key="sites.retention",
    module="shared.sites",
    title={"pl": "Zapytania ze strony", "en": "Website enquiries"},
    description={
        "pl": "Po jakim czasie firma usuwa dane osób z zapytań z formularza kontaktowego. "
        "Usunięcia nie da się cofnąć. W statystykach strony zostaje samo to, że zapytanie "
        "było.",
        "en": "How long the company keeps the personal data in messages from the contact "
        "form on its site. A removal cannot be undone. The site's statistics keep only the "
        "fact that an enquiry was made.",
    },
    permission=SETTINGS_MANAGE,
    area="privacy",
    # Turning it on removes people's data for good: never without a person.
    risk="irreversible",
    commands=("sites.settings_retention.read@1", "sites.settings_retention.update@1"),
    effects=_effects,
    settings=(
        SettingSpec(
            key=INQUIRIES,
            type="enum",
            default=RETENTION_OFF,
            scopes=("organization",),
            values=(
                (RETENTION_OFF, {"pl": "Nie usuwaj", "en": "Do not remove"}),
                *((str(count), _months(count)) for count in RETENTION_PERIODS),
            ),
            label={
                "pl": "Usuwaj zapytania po czasie",
                "en": "Remove enquiries after a time",
            },
            help={
                "pl": "Usuwane: imię, e-mail, telefon i treść zapytania razem z kopią, którą "
                "system zachował przy wysyłce powiadomienia. Zostaje: data i strona zapytania "
                "(statystyki). Poza systemem zostaje e-mail, który firma już dostała.",
                "en": "Removed: the name, e-mail, phone and text of the enquiry, with the "
                "copy the system kept when it sent the notification. Kept: the enquiry's "
                "date and page (statistics). Outside the system stays the e-mail the company "
                "already received.",
            },
            model_description="After how many months an enquiry from the site's contact form "
            "loses its personal data for good (name, e-mail, phone, text), in every copy the "
            "system stores; its date and page stay for the statistics; `off` removes nothing. "
            "The e-mail already delivered to the company's mailbox is outside the system and "
            "stays. Irreversible: a person in the company must decide, never the assistant "
            "on its own.",
        ),
    ),
)


def register_inquiry_retention() -> None:
    register_setting_group(RETENTION)
    for command in group_commands(RETENTION):
        register_command(command)
    register_retention_sweep(
        RetentionSweep(
            key="sites.inquiries",
            setting=INQUIRIES,
            due=lambda organization_id, cutoff: inquiries_due(organization_id, cutoff).count(),
        )
    )
