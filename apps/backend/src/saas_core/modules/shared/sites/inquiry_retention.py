"""How long the company keeps the enquiries from its site (settings plan D2,
owner answer 37a; ADR-078).

`sites.retention.inquiries`: off — as it always was, an enquiry stays until
the company is erased — or 12, 24 or 36 months after it arrived. An enquiry
is the personal data of somebody who is not the company's customer yet: a
name, an e-mail or a phone, and what they wrote. A run takes those out of
the enquiry and out of the stored notifications that carried it; the row
stays, so the site's statistics still know an enquiry was made.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db.models import QuerySet
from django.utils import timezone

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
    group_commands,
    months_of,
    register_command,
    register_retention_sweep,
    register_setting_group,
)
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.models import Organization, OrganizationSetting
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE
from saas_core.modules.shared.notifications.api import announce_retention, scrub_messages

from .models import SiteInquiry

INQUIRIES = "sites.retention.inquiries"
SWEEP = "sites.inquiries"
WHAT = {
    "pl": "dane osób i treść zapytań ze strony",
    "en": "the personal data and text of website enquiries",
}


def inquiries_due(organization_id: UUID, cutoff: datetime) -> QuerySet[SiteInquiry]:
    """The company's enquiries a run would strip at `cutoff`: those that
    arrived before it, read or not, and still hold the person's data."""
    return SiteInquiry.all_objects.filter(
        organization_id=organization_id, created_at__lt=cutoff, erased_at__isnull=True
    )


def erase_inquiries(organization_id: UUID, cutoff: datetime, limit: int) -> int:
    """Takes the person out of up to `limit` due enquiries, inside the
    company's tenant and the run's transaction: the name, the e-mail, the
    phone, the text, and the hashes that could confirm them. The stored
    notifications that carried the enquiry to the company's people lose their
    copy too — every recipient's, not only the first."""
    due = list(
        inquiries_due(organization_id, cutoff)
        .select_for_update(skip_locked=True)
        .order_by("id")[:limit]
    )
    now = timezone.now()
    for inquiry in due:
        marker = hashlib.sha256(f"erased:{inquiry.id}".encode()).hexdigest()
        inquiry.name = ""
        inquiry.email = ""
        inquiry.phone = ""
        inquiry.message = ""
        # A digest of the whole form could confirm a known text; the key came
        # from the visitor's browser. Neither is needed once the text is gone.
        inquiry.request_hash = marker
        inquiry.idempotency_key = f"erased:{inquiry.id}"
        inquiry.erased_at = now
        inquiry.save(
            update_fields=[
                "name",
                "email",
                "phone",
                "message",
                "request_hash",
                "idempotency_key",
                "erased_at",
            ]
        )
    scrub_messages(organization_id, [f"site-inquiry:{inquiry.id}" for inquiry in due])
    return len(due)


def starts_on(organization_id: UUID) -> date:
    """The first day a removal switched on now could happen, as the company
    reads its calendar."""
    zone = Organization.objects.values_list("timezone", flat=True).get(pk=organization_id)
    moment = timezone.now() + timedelta(days=RETENTION_GRACE_DAYS)
    return moment.astimezone(ZoneInfo(zone)).date()


def _effects(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[Effect, ...]:
    months = months_of(after["inquiries"])
    if months is None or after["inquiries"] == before["inquiries"]:
        return ()
    organization_id = require_tenant_context().organization_id
    count = inquiries_due(organization_id, cutoff_for(months)).count()
    day = starts_on(organization_id).isoformat()
    return (
        Effect(
            kind="erasure_scheduled",
            resource="sites.inquiry",
            resource_id="",
            summary={
                "pl": f"Zapytania starsze niż {months} miesięcy, których dotyczy teraz: {count}. "
                "Dane osoby i treść zostaną z nich usunięte bez możliwości przywrócenia, "
                f"najwcześniej {day}; z kolejnych — gdy minie ich termin. E-maile z "
                "zapytaniami, które już trafiły na skrzynki firmy, zostają tam. Właściciele "
                "firmy dostaną o tym e-mail.",
                "en": f"Enquiries older than {months} months, affected now: {count}. The "
                "person's data and the text will be removed from them for good, on "
                f"{day} at the earliest; from further ones when their time comes. The "
                "e-mails with enquiries already delivered to the company's mailboxes stay "
                "there. The company's owners get an e-mail about it.",
            },
        ),
    )


def _announce(before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    new, old = months_of(after["inquiries"]), months_of(before["inquiries"])
    if new is None or (old is not None and new >= old):
        return
    organization_id = require_tenant_context().organization_id
    version = (
        OrganizationSetting.objects.filter(organization_id=organization_id, key=INQUIRIES)
        .values_list("version", flat=True)
        .first()
    )
    announce_retention(
        key=INQUIRIES,
        what=WHAT,
        months=new,
        count=inquiries_due(organization_id, cutoff_for(new)).count(),
        starts_on=starts_on(organization_id),
        version=int(version or 0),
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
    on_changed=_announce,
    settings=(
        SettingSpec(
            key=INQUIRIES,
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
                "pl": "Usuwaj zapytania po czasie",
                "en": "Remove enquiries after a time",
            },
            help={
                "pl": "Usuwane: imię, e-mail, telefon i treść zapytania razem z kopią, którą "
                "system zachował przy wysyłce powiadomienia. Zostaje: data i strona zapytania "
                "(statystyki). Poza systemem zostaje e-mail, który firma już dostała. Po "
                f"włączeniu nic nie znika przez {RETENTION_GRACE_DAYS} dni.",
                "en": "Removed: the name, e-mail, phone and text of the enquiry, with the "
                "copy the system kept when it sent the notification. Kept: the enquiry's "
                "date and page (statistics). Outside the system stays the e-mail the company "
                "already received. After switching it on, nothing goes for "
                f"{RETENTION_GRACE_DAYS} days.",
            },
            model_description="After how many months an enquiry from the site's contact form "
            "loses its personal data for good (name, e-mail, phone, text), in every copy the "
            "system stores; its date and page stay for the statistics; `off` removes nothing. "
            "The e-mail already delivered to the company's mailbox is outside the system and "
            f"stays. Nothing is removed for {RETENTION_GRACE_DAYS} days after the value "
            "changes, and the owners are told by e-mail. Irreversible: a person in the "
            "company must decide, never the assistant on its own.",
        ),
    ),
)


def register_inquiry_retention() -> None:
    register_setting_group(RETENTION)
    for command in group_commands(RETENTION):
        register_command(command)
    register_retention_sweep(
        RetentionSweep(
            key=SWEEP,
            rule=company_months(INQUIRIES),
            due=lambda organization_id, cutoff: inquiries_due(organization_id, cutoff).count(),
            erase=erase_inquiries,
        )
    )
