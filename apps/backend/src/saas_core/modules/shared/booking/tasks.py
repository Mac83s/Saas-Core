from __future__ import annotations

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from saas_core.modules.core.organizations.tasks import InvalidTenantTaskContext, tenant_task_context
from saas_core.modules.shared.notifications.security import decrypt_secret
from saas_core.modules.shared.notifications.services import queue_email

from .models import Appointment, AppointmentStatus, ReminderRoute


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
                decrypt_secret(route.signed_tenant_context),
                expected_causation_id=f"booking:{route.appointment_id}",
            ):
                appointment = (
                    Appointment.all_objects.select_related("customer", "organization")
                    .filter(
                        pk=route.appointment_id,
                        status=AppointmentStatus.CONFIRMED,
                        reminder_sent_at__isnull=True,
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
                            "starts_at": appointment.starts_at.isoformat(),
                        },
                        idempotency_key=f"booking-reminder:{appointment.id}",
                        causation_id=f"booking:{appointment.id}",
                    )
                    appointment.reminder_sent_at = timezone.now()
                    appointment.save(update_fields=["reminder_sent_at", "updated_at"])
            with transaction.atomic():
                ReminderRoute.objects.filter(pk=route.pk, dispatched_at__isnull=True).update(
                    dispatched_at=timezone.now()
                )
            dispatched += 1
        except InvalidTenantTaskContext:
            continue
    return dispatched
