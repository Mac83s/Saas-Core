"""Public use-case API of the Booking module.

A vertical schedules its work as a booking appointment rather than growing a
second calendar: slots, availability, staff and cancellation already live here.
What it may touch is this module, not `booking.models` — the module contract
puts the public surface in `api.py`, and everything else is private.

`APPOINTMENT_MODEL` is the label a vertical points its own detail row at, so
`models.OneToOneField(APPOINTMENT_MODEL, …)` resolves lazily through Django's
app registry without importing a private model.
"""

from .models import AppointmentStatus
from .observers import (
    CANCELED,
    COMPLETED,
    CREATED,
    RESCHEDULED,
    AppointmentChange,
    register_appointment_observer,
)
from .services import (
    BOOKING_ENABLED,
    BOOKING_MANAGE,
    BOOKING_READ,
    AppointmentNotChangeable,
    BookingIdempotencyConflict,
    CreatedAppointment,
    SlotUnavailable,
    appointment_for_tenant,
    cancel_appointment,
    complete_appointment,
    create_appointment,
    list_appointments,
    reschedule_appointment,
    staff_for_membership,
)

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
    "RESCHEDULED",
    "AppointmentChange",
    "AppointmentNotChangeable",
    "AppointmentStatus",
    "BookingIdempotencyConflict",
    "CreatedAppointment",
    "SlotUnavailable",
    "appointment_for_tenant",
    "cancel_appointment",
    "complete_appointment",
    "create_appointment",
    "list_appointments",
    "register_appointment_observer",
    "reschedule_appointment",
    "staff_for_membership",
]
