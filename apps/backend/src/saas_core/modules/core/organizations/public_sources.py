"""Live records the public sees, by the module that owns them (ADR-074 pkt 7).

A published page is a snapshot, and its pictures are named by the snapshot. A
unit of a booking form or a product of a shop is live data: nothing publishes
it, so nothing but its own module knows what of it is shown. A module registers
a source here and whoever must respect it asks the registry instead of the
module — the registry lives in core because media depends on neither booking
nor the shop.

Today a source says one thing: which media its records show now. Media keeps
those objects when the asset is deleted from the library, as it keeps a
published page's. What else a source names — its public addresses, the facts
for structured data, the pictures a company's site may serve — joins the same
record with its first reader.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured


@dataclass(frozen=True, slots=True)
class PublicSource:
    #: `<module>.<what>`, e.g. `booking.units`.
    key: str
    #: `shown_media(organization_id)` → the ids of the media assets its
    #: records of that company show now. Called inside the company's tenant.
    shown_media: Callable[[UUID], Iterable[UUID]]


_sources: dict[str, PublicSource] = {}


def register_public_source(source: PublicSource) -> None:
    existing = _sources.get(source.key)
    if existing is not None and existing != source:
        raise ImproperlyConfigured(f"Publiczne źródło jest już zarejestrowane: {source.key}")
    _sources[source.key] = source


def shown_media_ids(organization_id: UUID) -> set[UUID]:
    """The media assets some live record of the company shows now. The caller
    holds the company's tenant."""
    shown: set[UUID] = set()
    for source in _sources.values():
        shown.update(source.shown_media(organization_id))
    return shown
