"""Where a booking or an order started, on the word of whoever sent the
customer (ADR-072 §11, slice 5h).

A company's own site and its office need no word: the server knows a public
form from the panel by itself. A page of the platform that sends a customer
on — the catalogue — hands them a token in the link's address, and the form
gives it back with the booking. The token says one channel and one company,
is signed with the deployment's key and ages out: a link copied elsewhere
stops counting as the catalogue's, and a token made for one company says
nothing at another's form.

It travels in the address and in the form's state, never in a cookie, and it
is a hint: a booking with no token, a forged one or one too old is taken all
the same, as one that came by itself.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from django.core import signing

#: The channel of a customer the platform's catalogue sent.
CATALOG = "catalog"
#: The channels a token can vouch for.
ORIGIN_CHANNELS = frozenset({CATALOG})
#: How long a link counts as its channel's after the page that carried it was
#: read. A month covers a guest who compares places and comes back; a year
#: would let one old bookmark claim every later booking.
ORIGIN_MAX_AGE = timedelta(days=30)
#: A token of ours is about 130 characters; what is longer is not one.
ORIGIN_TOKEN_MAX_LENGTH = 255

_SALT = "saas-core.origin.v1"


def issue_origin(channel: str, organization_id: UUID) -> str:
    """A token saying a customer of that company comes from `channel` now."""
    if channel not in ORIGIN_CHANNELS:
        raise ValueError(f"No origin token is issued for the channel {channel!r}.")
    return signing.dumps({"c": channel, "o": str(organization_id)}, salt=_SALT)


def read_origin(token: str, organization_id: UUID) -> str | None:
    """The channel a token vouches for at that company, or None: no token,
    not one of ours, too old, or issued for another company."""
    if not token or len(token) > ORIGIN_TOKEN_MAX_LENGTH:
        return None
    try:
        claims = signing.loads(token, salt=_SALT, max_age=ORIGIN_MAX_AGE)
    except signing.BadSignature:
        return None
    if not isinstance(claims, dict) or claims.get("o") != str(organization_id):
        return None
    channel = claims.get("c")
    return channel if channel in ORIGIN_CHANNELS else None
