from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from .context import TenantContext, require_tenant_context


@dataclass(frozen=True, slots=True)
class DomainEvent:
    id: UUID
    event_type: str
    version: int
    organization_id: UUID
    actor_id: UUID
    correlation_id: UUID
    causation_id: str
    payload: dict[str, Any]


type DomainEventHandler = Callable[[DomainEvent], None]


class DomainEventDeliveryError(RuntimeError):
    pass


_handlers: dict[tuple[str, int], list[DomainEventHandler]] = {}


def register_domain_event_handler(
    event_type: str,
    version: int,
    handler: DomainEventHandler,
) -> None:
    if not event_type or version <= 0:
        raise ValueError("Typ i wersja zdarzenia muszą być prawidłowe.")
    registered = _handlers.setdefault((event_type, version), [])
    if handler not in registered:
        registered.append(handler)


def dispatch_domain_event(*, context: TenantContext, event: DomainEvent) -> None:
    if require_tenant_context() != context or event.organization_id != context.organization_id:
        raise ValueError("Zdarzenie nie pasuje do aktywnego tenant context.")
    for handler in tuple(_handlers.get((event.event_type, event.version), ())):
        try:
            handler(event)
        except Exception as error:
            raise DomainEventDeliveryError("Handler zdarzenia domenowego zawiódł.") from error
