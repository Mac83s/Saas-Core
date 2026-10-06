"""Where a booking came from (ADR-072 §11, slice 5h).

The server knows two channels by itself: the team's own booking (`office`)
and the company's public form (`company_site`). The third needs somebody's
word: a guest the platform's catalogue sent carries its signed token in the
form's address, the form sends it back with the booking, and a token that
holds — ours, for this company, not too old — makes the booking the
catalogue's. The booking keeps the channel and the token that vouched for
it; its order copies the channel (ADR-073 §3).

A token never refuses a booking: without one, or with one that does not
hold, a booking from the form is the company site's.
"""

from __future__ import annotations

from saas_core.modules.core.organizations.api import read_origin
from saas_core.modules.core.organizations.context import require_tenant_context

from .models import BookingChannel
from .security import PUBLIC_BOOKING_ROLE


def booking_origin(origin: str = "") -> dict[str, str]:
    """`channel` and `origin_token` of a booking made now by the caller.
    `origin` is the token the public form got in its address, as sent."""
    context = require_tenant_context()
    if context.role_key != PUBLIC_BOOKING_ROLE:
        return {"channel": BookingChannel.OFFICE, "origin_token": ""}
    if read_origin(origin, context.organization_id) == BookingChannel.CATALOG:
        return {"channel": BookingChannel.CATALOG, "origin_token": origin}
    return {"channel": BookingChannel.COMPANY_SITE, "origin_token": ""}
