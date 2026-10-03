"""What a company states about itself to the outside world (ADR-071 pkt 16).

The business card owns these facts; whoever prints them — the sites' JSON-LD —
reads them here, because the card's module depends on the sites and not the
other way round. Facts are not translated: one company has one name, one
address and one phone in every language.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class OrganizationFacts:
    name: str
    #: The schema.org subtype of LocalBusiness the company's catalogue category
    #: names ("LodgingBusiness"); "" when the category names none.
    business_type: str = ""
    telephone: str = ""
    email: str = ""
    street_address: str = ""
    locality: str = ""
    region: str = ""
    #: ISO 3166-1 alpha-2, known only together with the locality.
    country: str = ""
    same_as: tuple[str, ...] = ()

    def as_snapshot(self) -> dict[str, Any]:
        """Plain data for a publication snapshot: only what is stated."""
        return {key: value for key, value in asdict(self).items() if value}


FactsSource = Callable[[UUID], OrganizationFacts | None]
_sources: list[FactsSource] = []


def register_organization_facts(source: FactsSource) -> None:
    """`source(organization_id)` → the company's facts, or None when it has
    none to state. Called inside the company's tenant context."""
    if source not in _sources:
        _sources.append(source)


def organization_facts(organization_id: UUID) -> OrganizationFacts | None:
    """The first source that knows the company; None when nobody does."""
    for source in _sources:
        facts = source(organization_id)
        if facts is not None:
            return facts
    return None
