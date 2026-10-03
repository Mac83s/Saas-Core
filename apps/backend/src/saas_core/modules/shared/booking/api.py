"""Public use-case API of the Booking module.

A vertical schedules its work as a booking appointment rather than growing a
second calendar: slots, availability, staff and cancellation already live here.
What it may touch is this module, not `booking.models` — the module contract
puts the public surface in `api.py`, and everything else is private.

`APPOINTMENT_MODEL` is the label a vertical points its own detail row at, so
`models.OneToOneField(APPOINTMENT_MODEL, …)` resolves lazily through Django's
app registry without importing a private model.
"""

from .crew import (
    CrewPerson,
    crew_member_filter,
    crew_people,
    join_visit_crew,
    leave_visit_crew,
    on_crew,
)
from .facts import (
    STAFF_PERFORMANCE_READ,
    Event,
    Metric,
    Period,
    StaffFacts,
    StaffSubject,
    register_staff_facts,
)
from .flags import register_appointment_flags
from .models import AppointmentStatus
from .observers import (
    CANCELED,
    COMPLETED,
    CREATED,
    NO_SHOW,
    RESCHEDULED,
    AppointmentChange,
    register_appointment_observer,
)
from .passing import closes_explicitly, has_passed
from .places import PlaceSuggestion, register_appointment_place, register_place_search
from .services import (
    BOOKING_ENABLED,
    BOOKING_MANAGE,
    BOOKING_READ,
    AppointmentNotChangeable,
    BookingIdempotencyConflict,
    CreatedAppointment,
    SlotUnavailable,
    VisitNotStartedYet,
    appointment_for_tenant,
    cancel_appointment,
    complete_appointment,
    create_appointment,
    list_appointments,
    mark_no_show,
    reschedule_appointment,
    staff_for_membership,
)
from .titles import register_appointment_title

#: Lazy reference for a vertical's `OneToOneField`/`ForeignKey`.
APPOINTMENT_MODEL = "booking.Appointment"

__all__ = [
    "APPOINTMENT_MODEL",
    "BOOKING_ENABLED",
    "BOOKING_MANAGE",
    "BOOKING_READ",
    "CANCELED",
    "COMPLETED",
    "CREATED",
    "NO_SHOW",
    "RESCHEDULED",
    "STAFF_PERFORMANCE_READ",
    "AppointmentChange",
    "AppointmentNotChangeable",
    "AppointmentStatus",
    "BookingIdempotencyConflict",
    "CreatedAppointment",
    "CrewPerson",
    "Event",
    "Metric",
    "Period",
    "PlaceSuggestion",
    "SlotUnavailable",
    "StaffFacts",
    "StaffSubject",
    "VisitNotStartedYet",
    "appointment_for_tenant",
    "cancel_appointment",
    "closes_explicitly",
    "complete_appointment",
    "create_appointment",
    "crew_member_filter",
    "crew_people",
    "has_passed",
    "join_visit_crew",
    "leave_visit_crew",
    "list_appointments",
    "mark_no_show",
    "on_crew",
    "register_appointment_flags",
    "register_appointment_observer",
    "register_appointment_place",
    "register_appointment_title",
    "register_place_search",
    "register_staff_facts",
    "reschedule_appointment",
    "staff_for_membership",
]
