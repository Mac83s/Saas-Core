"""Files an e-mail carries, resolved when it is delivered (HC-ADR-002, C5).

A message stores a reference (`<prefix>:<id>`), never the bytes: the owning
module registers a resolver for its prefix and returns the file at delivery
time, in the tenant context the message was queued in. So a report PDF is not
copied into the outbox and is never reachable through a public link.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Attachment:
    filename: str
    content: bytes
    mimetype: str


Resolver = Callable[[str], Attachment]
_RESOLVERS: dict[str, Resolver] = {}


def register_attachment_resolver(prefix: str, resolver: Resolver) -> None:
    """Called from the owning module's `AppConfig.ready`."""
    if ":" in prefix or not prefix:
        raise ValueError("Prefiks załącznika nie może zawierać dwukropka.")
    existing = _RESOLVERS.get(prefix)
    if existing is not None and existing is not resolver:
        raise ValueError(f"Prefiks załącznika {prefix} ma już inny resolver.")
    _RESOLVERS[prefix] = resolver


def is_known(reference: str) -> bool:
    prefix, _, value = reference.partition(":")
    return bool(value) and prefix in _RESOLVERS


def resolve_attachment(reference: str) -> Attachment:
    prefix, _, value = reference.partition(":")
    resolver = _RESOLVERS.get(prefix)
    if resolver is None or not value:
        raise LookupError(f"Nieznany załącznik {reference!r}.")
    return resolver(value)
