"""What other modules say about a company in the catalogue (ADR-072 §11,
slice 5h).

Profiles depend on no module that books, so such a module registers here, as
it does its search words (`register_catalog_terms`). Three things:

- a **badge** — a yes or no the listing shows and filters by („rezerwacja
  online”). The listing reads one public table and opens no tenant, so the
  answer is copied onto the company's row (`CatalogEntry.badges`) each time
  the row is written and each time a module reports a change
  (`catalog_changed`). The copy can lag what only the tenant knows — a plan
  that stopped covering bookings; the company's card and the form itself
  never do, they ask live;
- **what can be booked** — the company's form and the units it shows a
  guest, for the company's card and for a unit's own page under it
  (`/katalog/<miasto>/<firma>/<jednostka>`). Read live, inside the tenant
  the catalogue row named, each time the page is read;
- a **category hint** — the category the company's own setup points at (an
  offer made from a preset names one), offered while its card has none. A
  hint sets nothing: where a company stands is the company's choice.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured

#: `provider(organization_id)` → whether the company has the badge now. The
#: provider sets the tenant context it needs.
BadgeProvider = Callable[[UUID], bool]
_badges: dict[str, BadgeProvider] = {}


def register_catalog_badge(key: str, provider: BadgeProvider) -> None:
    """A module gives its tenants a badge of the listing. The key is the
    filter's value and what the page names in its own words."""
    existing = _badges.get(key)
    if existing is not None and existing != provider:
        raise ImproperlyConfigured(f"Odznaka katalogu jest już zarejestrowana: {key}")
    _badges[key] = provider


def badge_keys() -> list[str]:
    """The badges this product's catalogue has, for its filter."""
    return sorted(_badges)


def badges_of(organization_id: UUID) -> list[str]:
    """The badges the company has now, in key order."""
    return [key for key in sorted(_badges) if _badges[key](organization_id)]


@dataclass(frozen=True, slots=True)
class CatalogBooking:
    """What a module lets a visitor book at a company from the catalogue.
    Both answers are what the company's own public form would say: only what
    it takes online and shows a guest. Each sets its own tenant context."""

    #: `<module>.<what>`, e.g. `booking.form`.
    key: str
    #: `card(organization_id, locale)` → the company's form and the units it
    #: shows (`CatalogBookingSerializer` without `origin`), or None: nothing
    #: is booked online there now.
    card: Callable[[UUID, str], Mapping[str, Any] | None]
    #: `unit(organization_id, locale, slug)` → the unit at that address with
    #: the form it is booked on (`CatalogUnitPageSerializer` without the
    #: company and `origin`), or None: the form shows no such unit now.
    unit: Callable[[UUID, str, str], Mapping[str, Any] | None]


_bookings: dict[str, CatalogBooking] = {}


def register_catalog_booking(source: CatalogBooking) -> None:
    existing = _bookings.get(source.key)
    if existing is not None and existing != source:
        raise ImproperlyConfigured(
            f"Źródło rezerwacji katalogu jest już zarejestrowane: {source.key}"
        )
    _bookings[source.key] = source


def booking_card(organization_id: UUID, locale: str) -> Mapping[str, Any] | None:
    """What can be booked at the company now, by the first module that says."""
    for source in _bookings.values():
        card = source.card(organization_id, locale)
        if card is not None:
            return card
    return None


def booking_unit(organization_id: UUID, locale: str, slug: str) -> Mapping[str, Any] | None:
    """The unit at that address under the company's card, or None."""
    for source in _bookings.values():
        unit = source.unit(organization_id, locale, slug)
        if unit is not None:
            return unit
    return None


#: `provider(organization_id)` → the key of the category the company's setup
#: points at, or "". Called inside the company's tenant.
CategoryHint = Callable[[UUID], str]
_hints: dict[str, CategoryHint] = {}


def register_category_hint(name: str, provider: CategoryHint) -> None:
    _hints[name] = provider


def hinted_category(organization_id: UUID, known: Mapping[str, Any]) -> str:
    """The first hinted category that is one of the company's own
    dictionary (`known`: the categories of its organization type); "" when
    nobody hints or the hint is another type's category."""
    for name in sorted(_hints):
        hinted = _hints[name](organization_id)
        if hinted and hinted in known:
            return hinted
    return ""
