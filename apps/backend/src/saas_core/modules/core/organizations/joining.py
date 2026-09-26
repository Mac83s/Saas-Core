"""Modules take part in how people join, without Core importing them (ADR-058).

Booking links the calendar entry a person was added under to the account they
accept the invitation with; billing says how many accounts the plan allows.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from django.utils import timezone
from rest_framework.exceptions import APIException

from .authorization import authorize
from .models import Invitation, InvitationStatus, Membership, MembershipStatus, Organization
from .permissions import MEMBERS_READ

type InvitationAcceptedHandler = Callable[[Invitation, Membership], None]
type SeatLimit = Callable[[], int | None]

_accepted: list[InvitationAcceptedHandler] = []
_seat_limits: list[SeatLimit] = []


def _accounts(count: int) -> str:
    """ "1 konto", "3 konta", "5 kont" — Polish counts its nouns three ways."""
    if count == 1:
        return f"{count} konto"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} konta"
    return f"{count} kont"


class SeatLimitReached(APIException):
    status_code = 409
    default_code = "seat_limit_reached"

    def __init__(self, limit: int) -> None:
        super().__init__(
            detail=(
                f"Plan pozwala na {_accounts(limit)} w panelu. Pracownika bez konta "
                "dodasz bez limitu, a więcej kont daje wyższy plan."
            ),
            code=self.default_code,
        )


def register_invitation_accepted(handler: InvitationAcceptedHandler) -> None:
    if handler not in _accepted:
        _accepted.append(handler)


def announce_invitation_accepted(invitation: Invitation, membership: Membership) -> None:
    """Runs in the acceptance's transaction: a handler that fails undoes the join."""
    for handler in tuple(_accepted):
        handler(invitation, membership)


def register_seat_limit(limit: SeatLimit) -> None:
    if limit not in _seat_limits:
        _seat_limits.append(limit)


def seat_limit() -> int | None:
    """The fewest accounts any registered module allows; None: no limit."""
    limits = [value for value in (limit() for limit in _seat_limits) if value is not None]
    return min(limits) if limits else None


def seats_used(organization_id: UUID) -> int:
    """Accounts that log in or may start to: active members and open invitations.

    A suspended account does not log in and a person without an account is not
    one (owner's answer 5), so neither takes a seat.
    """
    members = Membership.objects.filter(
        organization_id=organization_id, status=MembershipStatus.ACTIVE
    ).count()
    invitations = Invitation.objects.filter(
        organization_id=organization_id,
        status=InvitationStatus.PENDING,
        expires_at__gt=timezone.now(),
    ).count()
    return members + invitations


def assert_seat_available(organization_id: UUID) -> None:
    """Refuses one more account over the plan's limit; accounts already there stay.

    The organization row is locked first, so two invitations sent at the same
    moment cannot both take the last seat.
    """
    limit = seat_limit()
    if limit is None:
        return
    list(Organization.objects.select_for_update().filter(pk=organization_id).values_list("pk"))
    if seats_used(organization_id) >= limit:
        raise SeatLimitReached(limit)


def current_seat_usage() -> tuple[int, int | None]:
    """How many of the plan's accounts the organization uses, and the limit."""
    context = authorize(MEMBERS_READ)
    return seats_used(context.organization_id), seat_limit()
