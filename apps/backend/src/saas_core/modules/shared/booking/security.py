from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from django.db import transaction

from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    set_local_organization_id,
)

PUBLIC_BOOKING_PERMISSIONS = frozenset({"booking.public.read", "booking.public.manage"})


def issue_self_service_token() -> tuple[str, str]:
    token = "bk_" + secrets.token_urlsafe(32)
    return token, token_digest(token)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


#: The role of the tenant context a customer's public link acts under.
PUBLIC_BOOKING_ROLE = "public_booking"

#: The organization's own reminder job (ADR-058 §7): it reads the visit and
#: queues one mail. The permission is a scope marker nobody's role carries.
REMINDER_ROLE = "booking_reminder"
REMINDER_PERMISSIONS = frozenset({"booking.reminder.send"})
#: The organization's own job that lets an unanswered request go (ADR-072
#: §9), in the reminders' pattern.
REQUEST_ROLE = "booking_requests"
REQUEST_PERMISSIONS = frozenset({"booking.request.expire"})
#: Booking's mails to the people on a visit (ADR-058 §9) are signed as the
#: organization's own job, with no permission of their own — not as the office
#: member who clicked, whose membership may be gone by the time a retry
#: delivers (the lesson of the reminders, ADR-058 §7).
NOTIFY_ROLE = "booking_notify"


def register_service_scopes() -> None:
    """The roles booking's own work is signed with (ADR-073 §5); from
    `BookingConfig.ready`."""
    from saas_core.modules.core.organizations.api import register_service_scope

    register_service_scope(PUBLIC_BOOKING_ROLE, PUBLIC_BOOKING_PERMISSIONS)
    # A reminder does one thing: its contract carries exactly its scope.
    register_service_scope(REMINDER_ROLE, REMINDER_PERMISSIONS, exact=True)
    register_service_scope(REQUEST_ROLE, REQUEST_PERMISSIONS, exact=True)
    register_service_scope(NOTIFY_ROLE)


@contextmanager
def public_booking_context(organization_id: UUID) -> Iterator[TenantContext]:
    context = TenantContext(
        organization_id=organization_id,
        membership_id=organization_id,
        actor_id=organization_id,
        role_key=PUBLIC_BOOKING_ROLE,
        permissions=PUBLIC_BOOKING_PERMISSIONS,
        principal_kind="service",
    )
    with transaction.atomic(), activate_tenant_context(context):
        set_local_organization_id(organization_id)
        yield context
