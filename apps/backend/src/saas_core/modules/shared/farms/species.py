"""Species the farm register knows (ADR-051).

A catalogue in code, not a table: a new species is an entry here, not a
migration of the model. Only active species may be recorded; the others are
prepared so that adding one is switching a flag, not a redesign.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Species:
    key: str
    label: dict[str, str]
    #: The national identifier as printed on the tag, after normalization
    #: (upper case, no spaces). Checked only for active species.
    identifier: re.Pattern[str]
    active: bool


SPECIES: dict[str, Species] = {
    "cattle": Species(
        key="cattle",
        label={"pl": "Bydło", "en": "Cattle"},
        # EU bovine tag: country code and up to 12 digits (PL uses exactly 12).
        identifier=re.compile(r"^[A-Z]{2}\d{6,14}$"),
        active=True,
    ),
    "sheep": Species(
        key="sheep",
        label={"pl": "Owce", "en": "Sheep"},
        identifier=re.compile(r"^[A-Z]{2}[0-9A-Z]{6,15}$"),
        active=False,
    ),
    "goat": Species(
        key="goat",
        label={"pl": "Kozy", "en": "Goats"},
        identifier=re.compile(r"^[A-Z]{2}[0-9A-Z]{6,15}$"),
        active=False,
    ),
    "horse": Species(
        key="horse",
        label={"pl": "Konie", "en": "Horses"},
        identifier=re.compile(r"^[0-9A-Z]{6,20}$"),
        active=False,
    ),
    "pig": Species(
        key="pig",
        label={"pl": "Świnie", "en": "Pigs"},
        identifier=re.compile(r"^[0-9A-Z]{4,20}$"),
        active=False,
    ),
}


def normalize_identifier(raw: str) -> str:
    """How a tag is typed differs; how it is stored and matched does not."""
    return re.sub(r"[\s-]", "", raw).upper()


def normalize_herd_number(raw: str) -> str:
    """`pl 012345678-001`, `PL012345678 001` and `PL012345678001` are one herd.

    Stored without separators, because the herd suffix is typed with a hyphen,
    a space or nothing, and the number is what a farmer's register is matched on.
    """
    return normalize_identifier(raw)


#: Country code and digits: the Polish producer number with its three-digit herd
#: suffix is PL + 12 digits (written PL012345678-001); other EU countries use the
#: same shape with their own code.
HERD_NUMBER = re.compile(r"^[A-Z]{2}\d{6,15}$")
TAX_ID = re.compile(r"^\d{10}$")
