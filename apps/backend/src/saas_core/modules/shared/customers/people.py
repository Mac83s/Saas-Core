"""A customer as a person in a command's answer (ADR-076, uzupełnienie
2026-10-04 „karty osób”).

A model gets a handle (`klient:k7m2q`); the person at the screen gets a card
with the name, the e-mail and the phone. Who may see which of those is not
this module's to say: the panel shows a customer on a visit and on an order,
and each has its own rule — whoever plans visits or goes to one sees the
phone, whoever reads orders sees the buyer. So the modules that show customers
say what the caller sees of each (`register_customer_viewer`), and a card is
what they allow together. A customer no module shows the caller cannot be
found by them either.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db.models import F, Func, Q, Value

from saas_core.modules.core.organizations.context import require_tenant_context

from .models import Customer

#: The kind of person a customer is, and the word its handles start with.
CUSTOMER = "customer"
PREFIX = "klient"
#: People a search answers with at once, and how many matches it looks at.
FOUND_AT_ONCE = 10
_LOOKED_AT = 200
#: Fewer digits than this are a number of something else, not a phone.
_PHONE_DIGITS = 5


@dataclass(frozen=True, slots=True)
class Sight:
    """What one module shows the caller of one customer: the name always."""

    #: The e-mail and the phone too.
    contact: bool = False
    #: Where the panel shows them: `{"title": {pl, en}, "href"}`.
    links: tuple[Mapping[str, Any], ...] = ()


type CustomerViewer = Callable[[Sequence[UUID]], Mapping[UUID, Sight]]

_viewers: dict[str, CustomerViewer] = {}


def register_customer_viewer(name: str, viewer: CustomerViewer) -> None:
    """From a module's `AppConfig.ready`: of the customers asked about, the
    ones the caller sees in that module's part of the panel, and how much of
    each. It answers for the active tenant and never raises for a caller
    without the right — it answers with nobody. `name` is what a search says
    the customer is known from (`bookings`, `orders`)."""
    _viewers[name] = viewer


def seen_customers(ids: Sequence[UUID]) -> dict[UUID, dict[str, Sight]]:
    """The customers the caller sees, each with what every module shows of it."""
    seen: dict[UUID, dict[str, Sight]] = {}
    if not ids:
        return seen
    for name in sorted(_viewers):
        for customer_id, sight in _viewers[name](ids).items():
            seen.setdefault(customer_id, {})[name] = sight
    return seen


def customer_cards(ids: Sequence[UUID]) -> dict[UUID, dict[str, Any]]:
    """The cards of the customers the caller sees, from their records as they
    are now: a customer taken out of the records has no contact left to show."""
    context = require_tenant_context()
    seen = seen_customers(ids)
    cards: dict[UUID, dict[str, Any]] = {}
    for customer in Customer.all_objects.filter(
        organization_id=context.organization_id, pk__in=list(seen)
    ):
        sights = seen[customer.id]
        contact = any(sight.contact for sight in sights.values())
        cards[customer.id] = {
            "name": customer.display_name,
            "email": (customer.email or None) if contact else None,
            "phone": (customer.phone or None) if contact else None,
            "links": [dict(link) for name in sorted(sights) for link in sights[name].links],
        }
    return cards


@dataclass(frozen=True, slots=True)
class Found:
    customer_id: UUID
    #: Which of the customer's own data the words matched: name, email, phone.
    matched: tuple[str, ...]
    #: The modules that show this customer to the caller.
    seen_in: tuple[str, ...]


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def find_customers(text: str) -> tuple[int, list[Found]]:
    """The caller's customers whose name, e-mail or phone the words match:
    how many there are, and the first of them. Every word must be in the
    name; the e-mail is matched as a whole; a phone by its digits, however it
    was spaced and with or without a country code."""
    context = require_tenant_context()
    words = text.split()
    whole = " ".join(words)
    if not whole:
        return 0, []
    name = Q()
    for word in words:
        name &= Q(display_name__icontains=word)
    match = name | Q(email__icontains=whole)
    digits = _digits(whole)
    # The last nine are the number without its country code.
    digits = digits[-9:] if len(digits) >= _PHONE_DIGITS else ""
    if digits:
        match |= Q(phone_digits__contains=digits)
    candidates = list(
        Customer.all_objects.filter(
            organization_id=context.organization_id, anonymized_at__isnull=True
        )
        .annotate(
            phone_digits=Func(
                F("phone"), Value(r"\D"), Value(""), Value("g"), function="regexp_replace"
            )
        )
        .filter(match)
        .order_by("-updated_at", "id")[:_LOOKED_AT]
    )
    seen = seen_customers([customer.id for customer in candidates])
    found = []
    for customer in candidates:
        if customer.id not in seen:
            continue
        folded = customer.display_name.casefold()
        matched = []
        if all(word.casefold() in folded for word in words):
            matched.append("name")
        if whole.casefold() in customer.email.casefold():
            matched.append("email")
        if digits and digits in _digits(customer.phone):
            matched.append("phone")
        found.append(Found(customer.id, tuple(matched), tuple(sorted(seen[customer.id]))))
    return len(found), found[:FOUND_AT_ONCE]
