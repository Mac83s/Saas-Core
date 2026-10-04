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

from saas_core.modules.core.identity.models import UserStatus
from saas_core.modules.core.organizations.api import setting
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
    AUDIENCE_CUSTOMER,
    AUDIENCE_STAFF,
    TEMPLATES,
    EmailTemplate,
    notify_in_app,
    public_url,
    queue_email,
    register_email_template,
    resolve_template_locale,
    staff_locale,
)
from saas_core.modules.shared.notifications.security import decrypt_secret

from .models import Appointment, AppointmentStatus, StaffMember
from .security import NOTIFY_ROLE

ASSIGNED = "booking.assigned"
UNASSIGNED = "booking.unassigned"
MOVED = "booking.moved"
CANCELED = "booking.canceled"

#: What the people who manage bookings hear when the company wants them told
#: (W8, `booking.notices.office`).
OFFICE_NEW = "booking.office_new"
OFFICE_WAITING = "booking.office_waiting"
OFFICE_CANCELED = "booking.office_canceled"
#: A booking that waited for its payment let its time go (ADR-072 §9).
OFFICE_EXPIRED = "booking.office_expired"
#: A customer asked for a booking the company answers itself, and one nobody
#: answered in its time. Told whatever the notices' switch says: an
#: unanswered request expires.
OFFICE_REQUEST = "booking.office_request"
OFFICE_REQUEST_EXPIRED = "booking.office_request_expired"
#: Who manages bookings: the queue and the calendar of everybody.
MANAGE_BOOKINGS = "booking.appointment.manage"


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
    # The customer's language, or the template's fallback when it has no such
    # version yet — the link then opens the page in the language of the mail.
    locale = resolve_template_locale(TEMPLATES[("booking.person_changed", 1)], customer.locale)
    token = decrypt_secret(appointment.self_service_token_ciphertext)
    with _as_the_organization(appointment.organization_id):
        queue_email(
            recipient_email=customer.email,
            template_key="booking.person_changed",
            template_version=2,
            locale=locale,
            template_context={
                "organization_name": organization.name,
                "starts_at": _local(appointment.starts_at, appointment.timezone, locale),
                "manage_url": manage_url(token, locale),
            },
            idempotency_key=f"booking-person:{appointment.id}:{appointment.crew_version}",
            causation_id=f"booking:{appointment.id}",
        )


def office_told(
    appointment: Appointment, kind: str, *, crew: Iterable[UUID] = (), always: bool = False
) -> None:
    """Everyone who manages bookings hears about a new online booking, a visit
    waiting for someone or a customer's cancellation — when the company says
    so (W8), or `always` for what waits for the company's own answer. The
    people on the visit heard already; nobody hears twice."""
    from .company_settings import OFFICE_NOTICES  # noqa: PLC0415 — it imports services

    if not always and not setting(OFFICE_NOTICES):
        return
    told = set(
        StaffMember.all_objects.filter(pk__in=list(crew), membership__isnull=False).values_list(
            "membership_id", flat=True
        )
    )
    managers = [
        membership
        for membership in Membership.objects.select_related("role", "user").filter(
            organization_id=appointment.organization_id,
            status=MembershipStatus.ACTIVE,
            user__status=UserStatus.ACTIVE,
        )
        if MANAGE_BOOKINGS in (membership.role.permissions or ()) and membership.id not in told
    ]
    _send(appointment, managers, kind, key="office", template=kind)


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
    memberships = Membership.objects.filter(
        pk__in=StaffMember.all_objects.filter(pk__in=people, membership__isnull=False).values(
            "membership_id"
        ),
        status=MembershipStatus.ACTIVE,
        user__status=UserStatus.ACTIVE,
    ).select_related("user")
    _send(
        appointment,
        list(memberships),
        kind,
        key=key,
        template=f"booking.staff_{kind.removeprefix('booking.')}",
        previous_starts_at=previous_starts_at,
    )


def _send(
    appointment: Appointment,
    memberships: list[Membership],
    kind: str,
    *,
    key: str,
    template: str,
    previous_starts_at: datetime | None = None,
) -> None:
    """The notice in the app and the mail, to each of these people but the
    one who made the change."""
    if not memberships:
        return
    actor_id = require_tenant_context().actor_id
    organization = Organization.objects.get(pk=appointment.organization_id)
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
                template_key=template,
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
                    "panel_url": public_url(locale, f"/panel/calendar?date={day.isoformat()}"),
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
    return staff_locale(organization_id=organization_id, user=user)


def manage_url(token: str, locale: str) -> str:
    """The customer's own page for the booking: change the time or cancel, in
    the customer's language — any content language, not only English (TL17)."""
    return public_url(locale, f"/booking/{token}")


def _local(value: datetime, zone: str, locale: str) -> str:
    from .services import local_time  # noqa: PLC0415 — services imports this module

    return local_time(value, zone, locale)


def _template(
    key: str,
    subjects: dict[str, str],
    bodies: dict[str, str],
    fields: set[str],
    audience: str = AUDIENCE_STAFF,
    version: int = 1,
) -> None:
    register_email_template(
        EmailTemplate(
            key=key,
            version=version,
            category="required",
            subjects=subjects,
            bodies=bodies,
            allowed_context=frozenset(fields),
            audience=audience,
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
    for key, subject, body in (
        (
            OFFICE_NEW,
            {"pl": "Nowa rezerwacja online", "en": "A new online booking"},
            {
                "pl": "<p>{organization_name}: nowa rezerwacja online na {starts_at}.</p>",
                "en": "<p>{organization_name}: a new online booking for {starts_at}.</p>",
            },
        ),
        (
            OFFICE_WAITING,
            {"pl": "Wizyta czeka na przydzielenie", "en": "A visit waits for someone"},
            {
                "pl": "<p>{organization_name}: wizyta {starts_at} czeka na przydzielenie "
                "osoby.</p>",
                "en": "<p>{organization_name}: the visit at {starts_at} waits for someone "
                "to be assigned.</p>",
            },
        ),
        (
            OFFICE_CANCELED,
            {"pl": "Klient odwołał wizytę", "en": "A customer called a visit off"},
            {
                "pl": "<p>{organization_name}: klient odwołał wizytę {starts_at}.</p>",
                "en": "<p>{organization_name}: a customer called off the visit at {starts_at}.</p>",
            },
        ),
        (
            OFFICE_REQUEST,
            {"pl": "Prośba o rezerwację czeka na odpowiedź", "en": "A booking request waits"},
            {
                "pl": "<p>{organization_name}: klient prosi o rezerwację na {starts_at}. "
                "Przyjmij ją albo odmów — bez odpowiedzi prośba wygaśnie.</p>",
                "en": "<p>{organization_name}: a customer asks for a booking for "
                "{starts_at}. Accept or decline it — unanswered, the request expires.</p>",
            },
        ),
        (
            OFFICE_REQUEST_EXPIRED,
            {
                "pl": "Prośba o rezerwację wygasła bez odpowiedzi",
                "en": "A booking request expired unanswered",
            },
            {
                "pl": "<p>{organization_name}: prośba o rezerwację na {starts_at} wygasła, bo "
                "nikt na nią nie odpowiedział. Termin jest znowu wolny.</p>",
                "en": "<p>{organization_name}: the request for a booking for {starts_at} "
                "expired because nobody answered it. The time is free again.</p>",
            },
        ),
        (
            OFFICE_EXPIRED,
            {"pl": "Rezerwacja wygasła bez wpłaty", "en": "A booking expired unpaid"},
            {
                "pl": "<p>{organization_name}: rezerwacja na {starts_at} wygasła, bo wpłata "
                "nie dotarła w terminie. Termin jest znowu wolny.</p>",
                "en": "<p>{organization_name}: the booking for {starts_at} expired because "
                "its payment did not arrive in time. The time is free again.</p>",
            },
        ),
    ):
        _template(
            key,
            subject,
            {"pl": body["pl"] + look_pl, "en": body["en"] + look_en},
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
        audience=AUDIENCE_CUSTOMER,
    )
    # TL17: and in German; v1 stays for mails queued before it.
    _template(
        "booking.person_changed",
        {
            "pl": "Zmiana osoby przy Twojej wizycie",
            "en": "A change to your visit",
            "de": "Eine Änderung an Ihrem Termin",
        },
        {
            "pl": (
                "<p>W Twojej wizycie w {organization_name} ({starts_at}) zmieniła się osoba, "
                'która Cię przyjmie.</p><p><a href="{manage_url}">Zobacz swoją rezerwację</a></p>'
            ),
            "en": (
                "<p>The person who will see you at {organization_name} ({starts_at}) has "
                'changed.</p><p><a href="{manage_url}">See your booking</a></p>'
            ),
            "de": (
                "<p>Bei Ihrem Termin bei {organization_name} ({starts_at}) hat sich die Person "
                "geändert, die Sie betreut.</p>"
                '<p><a href="{manage_url}">Ihre Buchung ansehen</a></p>'
            ),
        },
        {"organization_name", "starts_at", "manage_url"},
        audience=AUDIENCE_CUSTOMER,
        version=2,
    )
    # A booking that waited for its payment and did not get it (ADR-072 §9).
    _template(
        "booking.pending_expired",
        {
            "pl": "Rezerwacja wygasła",
            "en": "Your booking has expired",
            "de": "Ihre Buchung ist verfallen",
        },
        {
            "pl": (
                "<p>Rezerwacja w {organization_name} na {starts_at} wygasła, bo wpłata nie "
                "dotarła w terminie.</p>"
                "<p>Jeśli przelew jest już w drodze albo chcesz zarezerwować ponownie, "
                "skontaktuj się z {organization_name}.</p>"
            ),
            "en": (
                "<p>Your booking at {organization_name} for {starts_at} has expired because "
                "the payment did not arrive in time.</p>"
                "<p>If your transfer is on its way, or you want to book again, please "
                "contact {organization_name}.</p>"
            ),
            "de": (
                "<p>Ihre Buchung bei {organization_name} für {starts_at} ist verfallen, weil "
                "die Zahlung nicht rechtzeitig eingegangen ist.</p>"
                "<p>Ist Ihre Überweisung bereits unterwegs oder möchten Sie erneut buchen, "
                "wenden Sie sich bitte an {organization_name}.</p>"
            ),
        },
        {"organization_name", "starts_at"},
        audience=AUDIENCE_CUSTOMER,
    )
    # A booking the company answers itself (ADR-072 §9): what the customer
    # hears when they ask, and each way the answer can go.
    _template(
        "booking.request_received",
        {
            "pl": "Prośba o rezerwację została wysłana",
            "en": "Your booking request was sent",
            "de": "Ihre Buchungsanfrage wurde gesendet",
        },
        {
            "pl": (
                "<p>{organization_name} dostała Twoją prośbę o rezerwację na {starts_at}. "
                "Termin jest dla Ciebie wstrzymany, a odpowiedź dostaniesz do {answer_by}.</p>"
                '<p><a href="{manage_url}">Zobacz prośbę albo z niej zrezygnuj</a></p>'
            ),
            "en": (
                "<p>{organization_name} has received your booking request for {starts_at}. "
                "The time is held for you, and you will get an answer by {answer_by}.</p>"
                '<p><a href="{manage_url}">See your request or withdraw it</a></p>'
            ),
            "de": (
                "<p>{organization_name} hat Ihre Buchungsanfrage für {starts_at} erhalten. "
                "Der Termin ist für Sie reserviert; eine Antwort erhalten Sie bis "
                "{answer_by}.</p>"
                '<p><a href="{manage_url}">Anfrage ansehen oder zurückziehen</a></p>'
            ),
        },
        {"organization_name", "starts_at", "answer_by", "manage_url"},
        audience=AUDIENCE_CUSTOMER,
    )
    _template(
        "booking.request_accepted",
        {
            "pl": "Prośba o rezerwację została przyjęta",
            "en": "Your booking request was accepted",
            "de": "Ihre Buchungsanfrage wurde angenommen",
        },
        {
            "pl": (
                "<p>{organization_name} przyjęła Twoją prośbę o rezerwację na {starts_at}.</p>"
                "<p>Rezerwacja czeka teraz na wpłatę — dane do przelewu wysyłamy w osobnej "
                "wiadomości. Potwierdzenie przyjdzie po wpłacie.</p>"
            ),
            "en": (
                "<p>{organization_name} has accepted your booking request for {starts_at}.</p>"
                "<p>The booking now waits for your payment — the transfer details come in a "
                "separate message. The confirmation follows once the payment arrives.</p>"
            ),
            "de": (
                "<p>{organization_name} hat Ihre Buchungsanfrage für {starts_at} "
                "angenommen.</p>"
                "<p>Die Buchung wartet nun auf Ihre Zahlung — die Überweisungsdaten senden "
                "wir in einer separaten Nachricht. Die Bestätigung folgt nach "
                "Zahlungseingang.</p>"
            ),
        },
        {"organization_name", "starts_at"},
        audience=AUDIENCE_CUSTOMER,
    )
    _template(
        "booking.request_declined",
        {
            "pl": "Prośba o rezerwację nie została przyjęta",
            "en": "Your booking request was declined",
            "de": "Ihre Buchungsanfrage wurde abgelehnt",
        },
        {
            "pl": (
                "<p>Niestety {organization_name} nie może przyjąć Twojej rezerwacji na "
                "{starts_at}.</p>"
                "<p>Jeśli chcesz umówić inny termin, skontaktuj się z {organization_name}.</p>"
            ),
            "en": (
                "<p>Unfortunately {organization_name} cannot take your booking for "
                "{starts_at}.</p>"
                "<p>If you would like another time, please contact {organization_name}.</p>"
            ),
            "de": (
                "<p>Leider kann {organization_name} Ihre Buchung für {starts_at} nicht "
                "annehmen.</p>"
                "<p>Für einen anderen Termin wenden Sie sich bitte an {organization_name}.</p>"
            ),
        },
        {"organization_name", "starts_at"},
        audience=AUDIENCE_CUSTOMER,
    )
    _template(
        "booking.request_expired",
        {
            "pl": "Prośba o rezerwację wygasła",
            "en": "Your booking request has expired",
            "de": "Ihre Buchungsanfrage ist verfallen",
        },
        {
            "pl": (
                "<p>{organization_name} nie odpowiedziała w terminie na Twoją prośbę o "
                "rezerwację na {starts_at}, więc prośba wygasła.</p>"
                "<p>Jeśli nadal chcesz zarezerwować, skontaktuj się z {organization_name}.</p>"
            ),
            "en": (
                "<p>{organization_name} did not answer your booking request for {starts_at} "
                "in time, so the request has expired.</p>"
                "<p>If you still want to book, please contact {organization_name}.</p>"
            ),
            "de": (
                "<p>{organization_name} hat Ihre Buchungsanfrage für {starts_at} nicht "
                "rechtzeitig beantwortet, daher ist die Anfrage verfallen.</p>"
                "<p>Wenn Sie weiterhin buchen möchten, wenden Sie sich bitte an "
                "{organization_name}.</p>"
            ),
        },
        {"organization_name", "starts_at"},
        audience=AUDIENCE_CUSTOMER,
    )
