"""What the removal of personal data after a time (D1–D2, answer 37a) needs
from notifications: the copies a removed record left in stored messages go
with it, and the company's owners hear when a removal is switched on."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from uuid import UUID

from django.conf import settings

from saas_core.modules.core.identity.models import UserStatus
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.models import (
    Membership,
    MembershipStatus,
    Organization,
)

from .models import NotificationMessage
from .services import queue_email, scrub_message_now, staff_locale
from .templates import EmailTemplate, register_email_template

NOTICE = "system.retention_scheduled"


def scrub_messages(
    organization_id: UUID, causation_ids: Iterable[str], *, to_customers_only: bool = False
) -> int:
    """Scrubs now, whatever their age, the stored messages a removed record
    caused — inside the company's tenant and the caller's transaction. With
    `to_customers_only`, a mail to one of the company's own people about the
    same record keeps its recipient: it held none of the removed person's
    data. Returns how many were scrubbed."""
    ids = list(causation_ids)
    if not ids:
        return 0
    messages = NotificationMessage.all_objects.select_for_update().filter(
        organization_id=organization_id, causation_id__in=ids
    )
    if to_customers_only:
        messages = messages.filter(recipient_user__isnull=True)
    # A message already scrubbed has no tenant contract left.
    due = list(messages.exclude(signed_tenant_context=""))
    for message in due:
        scrub_message_now(message)
    return len(due)


def register_retention_notice() -> None:
    register_email_template(
        EmailTemplate(
            key=NOTICE,
            version=1,
            category="required",
            subjects={
                "pl": "Włączono automatyczne usuwanie danych osobowych",
                "en": "Automatic removal of personal data was switched on",
            },
            bodies={
                "pl": (
                    "<p>W firmie {organization_name} {actor} włączył(a) automatyczne usuwanie: "
                    "{what}, po {months} miesiącach.</p>"
                    "<p>Teraz dotyczy: {count}. Usuwanie zacznie się {starts_on} i nie da się "
                    "go cofnąć — usuniętych danych nie przywrócimy.</p>"
                    "<p>Jeśli to pomyłka, wyłącz je przed tym dniem: {settings_url}</p>"
                ),
                "en": (
                    "<p>In {organization_name}, {actor} switched on automatic removal: {what}, "
                    "after {months} months.</p>"
                    "<p>Affected now: {count}. The removal starts on {starts_on} and cannot be "
                    "undone — removed data will not be restored.</p>"
                    "<p>If this is a mistake, switch it off before that day: {settings_url}</p>"
                ),
            },
            allowed_context=frozenset({
                "organization_name",
                "actor",
                "what",
                "months",
                "count",
                "starts_on",
                "settings_url",
            }),
        )
    )


def announce_retention(
    *, key: str, what: Mapping[str, str], months: int, count: int, starts_on: date, version: int
) -> int:
    """Tells every active owner, in the language of their panel, that the
    company switched a removal on (or made it sooner): who, what, how many
    now, from which day, and where to switch it off. Queued in the change's
    own transaction, so no change without the mail and no mail without the
    change. Returns how many were queued."""
    context = require_tenant_context()
    organization = Organization.objects.get(pk=context.organization_id)
    people = Membership.objects.select_related("user", "role").filter(
        organization_id=organization.id,
        status=MembershipStatus.ACTIVE,
        user__status=UserStatus.ACTIVE,
    )
    actor = next((m.user for m in people if m.user_id == context.actor_id), None)
    name = (
        " ".join(part for part in (actor.first_name, actor.last_name) if part) or actor.email
        if actor is not None
        else "—"
    )
    queued = 0
    for member in people:
        if member.role.key != "owner":
            continue
        locale = staff_locale(organization_id=organization.id, user=member.user)
        base = settings.FRONTEND_BASE_URL.rstrip("/") + ("/en" if locale == "en" else "")
        _, created = queue_email(
            recipient_email=member.user.email,
            recipient_user=member.user,
            template_key=NOTICE,
            template_version=1,
            locale=locale,
            template_context={
                "organization_name": organization.name,
                "actor": name,
                "what": what.get(locale) or what["pl"],
                "months": str(months),
                "count": str(count),
                "starts_on": starts_on.isoformat(),
                "settings_url": f"{base}/panel/settings/privacy",
            },
            idempotency_key=f"retention-notice:{key}:{version}:{member.user_id}",
            causation_id=f"retention-notice:{key}",
        )
        queued += int(created)
    return queued
