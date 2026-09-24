from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from saas_core.modules.core.organizations.tasks import InvalidTenantTaskContext, tenant_task_context
from saas_core.modules.shared.notifications.security import decrypt_secret
from saas_core.modules.shared.notifications.services import queue_email

from .models import Appointment, AppointmentStatus, ReminderRoute
from .services import local_time

logger = logging.getLogger("saas_core.security")


@shared_task  # type: ignore[untyped-decorator]
def dispatch_booking_reminders() -> int:
    dispatched = 0
    routes = list(
        ReminderRoute.objects.filter(
            dispatched_at__isnull=True, due_at__lte=timezone.now()
        ).order_by("due_at")[:100]
    )
    for route in routes:
        try:
            with tenant_task_context(
                _contract(route),
                expected_causation_id=f"booking:{route.appointment_id}",
                # Due when the visit is, which can be further off than the TTL.
                expires=False,
            ):
                # Locked, so a move committing meanwhile is read here rather
                # than overwritten; a move re-arms to a later due time.
                appointment = (
                    Appointment.all_objects.select_for_update(of=("self",))
                    .select_related("customer", "organization")
                    .filter(
                        pk=route.appointment_id,
                        status=AppointmentStatus.CONFIRMED,
                        reminder_sent_at__isnull=True,
                        reminder_due_at__lte=timezone.now(),
                    )
                    .first()
                )
                if appointment and appointment.customer.email:
                    queue_email(
                        recipient_email=appointment.customer.email,
                        template_key="booking.reminder",
                        template_version=1,
                        locale=appointment.customer.locale,
                        template_context={
                            "organization_name": appointment.organization.name,
                            "starts_at": local_time(
                                appointment.starts_at,
                                appointment.timezone,
                                appointment.customer.locale,
                            ),
                        },
                        # One per arming: a move re-arms to a later due time,
                        # even back to a start already reminded, and a retry
                        # of this arming is not sent twice.
                        idempotency_key=(
                            f"booking-reminder:{appointment.id}:{appointment.reminder_due_at}"
                        ),
                        causation_id=f"booking:{appointment.id}",
                    )
                    appointment.reminder_sent_at = timezone.now()
                    appointment.save(update_fields=["reminder_sent_at", "updated_at"])
            dispatched += 1
        except InvalidTenantTaskContext as error:
            # A contract that does not open now never will (undecryptable, an
            # inactive organization, a membership since revoked). Left
            # unmarked, it would head the queue forever (ADR-058 §7).
            logger.warning(
                "booking_reminder_route_rejected",
                extra={
                    "security_event": "booking.reminder_route_rejected",
                    "route_id": str(route.pk),
                    "reason": str(error),
                },
            )
        with transaction.atomic():
            # Only the arming this run read: a move re-arms with another due time.
            ReminderRoute.objects.filter(
                pk=route.pk, dispatched_at__isnull=True, due_at=route.due_at
            ).update(dispatched_at=timezone.now())
    return dispatched


def _contract(route: ReminderRoute) -> str:
    try:
        return decrypt_secret(route.signed_tenant_context)
    except RuntimeError as error:
        # A key since rotated: no later run decrypts it either.
        raise InvalidTenantTaskContext(str(error)) from error
