"""What people hear about the visits they are on (ADR-058 §9, answer 6).

A person with an active account learns in the app and at once by e-mail that
they were put on a visit, taken off it, or that it moved or was called off.
Nobody hears about a change they made themselves, and a person without an
account has nobody to tell — the office phones them.

The e-mail says the company, the time and where to look, never the customer
or the service: in a clinic either one is health data in somebody's inbox.
The app says the service, because the panel is where the details live.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings

from saas_core.modules.core.identity.models import UserStatus
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    current_tenant_context,
    require_tenant_context,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    MembershipStatus,
    Organization,
)
from saas_core.modules.shared.notifications.api import (
    EmailTemplate,
    notify_in_app,
    queue_email,
    register_email_template,
)
from saas_core.modules.shared.notifications.models import NotificationPreference
from saas_core.modules.shared.notifications.security import decrypt_secret

from .models import Appointment, AppointmentStatus, StaffMember

ASSIGNED = "booking.assigned"
UNASSIGNED = "booking.unassigned"
MOVED = "booking.moved"
CANCELED = "booking.canceled"

#: The role of the context the mails are signed with: the organization's own
#: job, not the office member who clicked — that membership may be gone by the
#: time a retry delivers (the lesson of the reminders, ADR-058 §7).
NOTIFY_ROLE = "booking_notify"


def staff_assigned(appointment: Appointment, staff_ids: Iterable[UUID]) -> None:
    _tell(appointment, staff_ids, ASSIGNED, key=f"{appointment.crew_version}")


def staff_unassigned(appointment: Appointment, staff_ids: Iterable[UUID]) -> None:
    _tell(appointment, staff_ids, UNASSIGNED, key=f"{appointment.crew_version}")


def staff_moved(
    appointment: Appointment,
    staff_ids: Iterable[UUID],
    *,
    previous_starts_at: datetime,
    mutation_id: UUID,
) -> None:
    _tell(
        appointment,
        staff_ids,
        MOVED,
        key=str(mutation_id),
        previous_starts_at=previous_starts_at,
    )


def staff_canceled(appointment: Appointment, staff_ids: Iterable[UUID]) -> None:
    _tell(appointment, staff_ids, CANCELED, key="once")


def customer_person_changed(appointment: Appointment, *, previous_lead_id: UUID) -> None:
    """The customer saw who would come — chose them, or read the name on the
    confirmation — and it is somebody else now (answer 2A, 28.09). The mail
    names nobody; the booking's own page shows the new name."""
    customer = appointment.customer
    if (
        not customer.email
        or appointment.status != AppointmentStatus.CONFIRMED
        or customer.anonymized_at
    ):
        return
    previous = StaffMember.all_objects.filter(pk=previous_lead_id).first()
    shown = appointment.requested_staff_id is not None or (
        previous is not None and previous.profile_id is not None
    )
    if not shown:
        return
    organization = Organization.objects.get(pk=appointment.organization_id)
    locale = customer.locale if customer.locale in {"pl", "en"} else "pl"
    token = decrypt_secret(appointment.self_service_token_ciphertext)
    with _as_the_organization(appointment.organization_id):
        queue_email(
            recipient_email=customer.email,
            template_key="booking.person_changed",
            template_version=1,
            locale=locale,
            template_context={
                "organization_name": organization.name,
                "starts_at": _local(appointment.starts_at, appointment.timezone, locale),
                "manage_url": manage_url(token, locale),
            },
            idempotency_key=f"booking-person:{appointment.id}:{appointment.crew_version}",
            causation_id=f"booking:{appointment.id}",
        )


def _tell(
    appointment: Appointment,
    staff_ids: Iterable[UUID],
    kind: str,
    *,
    key: str,
    previous_starts_at: datetime | None = None,
) -> None:
    people = list(staff_ids)
    if not people:
        return
    context = require_tenant_context()
    actor_id = context.actor_id
    organization = Organization.objects.get(pk=appointment.organization_id)
    memberships = Membership.objects.filter(
        pk__in=StaffMember.all_objects.filter(pk__in=people, membership__isnull=False).values(
            "membership_id"
        ),
        status=MembershipStatus.ACTIVE,
        user__status=UserStatus.ACTIVE,
    ).select_related("user")
    payload: dict[str, Any] = {
        "appointment_id": str(appointment.id),
        "starts_at": appointment.starts_at.isoformat(),
        "timezone": appointment.timezone,
        "service_name": appointment.service_name,
        **(
            {"previous_starts_at": previous_starts_at.isoformat()}
            if previous_starts_at is not None
            else {}
        ),
    }
    with _as_the_organization(appointment.organization_id):
        for membership in memberships:
            user = membership.user
            if user.id == actor_id:
                continue
            identity = f"{kind}:{appointment.id}:{key}:{user.id}"
            notify_in_app(
                organization_id=appointment.organization_id,
                user_id=user.id,
                kind=kind,
                payload=payload,
                idempotency_key=identity,
            )
            locale = _locale(appointment.organization_id, user)
            day = appointment.starts_at.astimezone(ZoneInfo(appointment.timezone)).date()
            queue_email(
                recipient_email=user.email,
                template_key=f"booking.staff_{kind.removeprefix('booking.')}",
                template_version=1,
                locale=locale,
                template_context={
                    "organization_name": organization.name,
                    "starts_at": _local(appointment.starts_at, appointment.timezone, locale),
                    **(
                        {
                            "previous_starts_at": _local(
                                previous_starts_at, appointment.timezone, locale
                            )
                        }
                        if previous_starts_at is not None
                        else {}
                    ),
                    "panel_url": f"{_base(locale)}/panel/calendar?date={day.isoformat()}",
                },
                idempotency_key=identity,
                causation_id=f"booking:{appointment.id}",
                recipient_user=user,
            )


@contextmanager
def _as_the_organization(organization_id: UUID) -> Iterator[None]:
    outer = current_tenant_context()
    if outer is not None and outer.principal_kind == "service":
        yield
        return
    context = TenantContext(
        organization_id=organization_id,
        membership_id=organization_id,
        actor_id=organization_id,
        role_key=NOTIFY_ROLE,
        permissions=frozenset(),
        principal_kind="service",
    )
    with activate_tenant_context(context):
        yield


def _locale(organization_id: UUID, user: Any) -> str:
    preference = NotificationPreference.all_objects.filter(
        organization_id=organization_id, user_id=user.id
    ).first()
    value = str(preference.locale) if preference is not None else str(user.locale or "pl")
    return value if value in {"pl", "en"} else "pl"


def manage_url(token: str, locale: str) -> str:
    """The customer's own page for the booking: change the time or cancel."""
    return f"{_base(locale)}/booking/{token}"


def _base(locale: str) -> str:
    return settings.FRONTEND_BASE_URL.rstrip("/") + ("/en" if locale == "en" else "")


def _local(value: datetime, zone: str, locale: str) -> str:
    from .services import local_time  # noqa: PLC0415 — services imports this module

    return local_time(value, zone, locale)


def _template(key: str, subjects: dict[str, str], bodies: dict[str, str], fields: set[str]) -> None:
    register_email_template(
        EmailTemplate(
            key=key,
            version=1,
            category="required",
            subjects=subjects,
            bodies=bodies,
            allowed_context=frozenset(fields),
        )
    )


def register_templates() -> None:
    """The mails this module sends to its own people; called from `ready()`."""
    look_pl = '<p><a href="{panel_url}">Zobacz w kalendarzu</a></p>'
    look_en = '<p><a href="{panel_url}">Open the calendar</a></p>'
    _template(
        "booking.staff_assigned",
        {"pl": "Nowa wizyta w Twoim kalendarzu", "en": "A new visit in your calendar"},
        {
            "pl": "<p>{organization_name}: przydzielono Cię do wizyty {starts_at}.</p>" + look_pl,
            "en": "<p>{organization_name}: you were put on a visit at {starts_at}.</p>" + look_en,
        },
        {"organization_name", "starts_at", "panel_url"},
    )
    _template(
        "booking.staff_unassigned",
        {"pl": "Zmiana w Twoim kalendarzu", "en": "A change in your calendar"},
        {
            "pl": "<p>{organization_name}: usunięto Cię z wizyty {starts_at}.</p>" + look_pl,
            "en": "<p>{organization_name}: you are no longer on the visit at {starts_at}.</p>"
            + look_en,
        },
        {"organization_name", "starts_at", "panel_url"},
    )
    _template(
        "booking.staff_moved",
        {"pl": "Wizyta przełożona", "en": "A visit was moved"},
        {
            "pl": (
                "<p>{organization_name}: wizyta z {previous_starts_at} "
                "jest teraz {starts_at}.</p>" + look_pl
            ),
            "en": (
                "<p>{organization_name}: the visit at {previous_starts_at} "
                "is now at {starts_at}.</p>" + look_en
            ),
        },
        {"organization_name", "starts_at", "previous_starts_at", "panel_url"},
    )
    _template(
        "booking.staff_canceled",
        {"pl": "Wizyta odwołana", "en": "A visit was called off"},
        {
            "pl": "<p>{organization_name}: wizyta {starts_at} została odwołana.</p>" + look_pl,
            "en": "<p>{organization_name}: the visit at {starts_at} was called off.</p>" + look_en,
        },
        {"organization_name", "starts_at", "panel_url"},
    )
    _template(
        "booking.person_changed",
        {"pl": "Zmiana osoby przy Twojej wizycie", "en": "A change to your visit"},
        {
            "pl": (
                "<p>W Twojej wizycie w {organization_name} ({starts_at}) zmieniła się osoba, "
                'która Cię przyjmie.</p><p><a href="{manage_url}">Zobacz swoją rezerwację</a></p>'
            ),
            "en": (
                "<p>The person who will see you at {organization_name} ({starts_at}) has "
                'changed.</p><p><a href="{manage_url}">See your booking</a></p>'
            ),
        },
        {"organization_name", "starts_at", "manage_url"},
    )
