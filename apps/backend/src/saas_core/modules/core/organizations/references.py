from __future__ import annotations

import re
from typing import Protocol
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured

from .context import TenantContext, require_tenant_context


class ResourceReferenceRejected(RuntimeError):
    pass


class ResourceReferenceConflict(RuntimeError):
    pass


class ResourceReferenceHandler(Protocol):
    def record(
        self,
        *,
        context: TenantContext,
        owner_type: str,
        owner_id: UUID,
        resource_ids: tuple[UUID, ...],
    ) -> tuple[UUID, ...]: ...

    def list_ids(
        self,
        *,
        context: TenantContext,
        owner_type: str,
        owner_id: UUID,
    ) -> tuple[UUID, ...]: ...


_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_handlers: dict[str, ResourceReferenceHandler] = {}


def register_resource_reference_handler(
    resource_type: str,
    handler: ResourceReferenceHandler,
) -> None:
    if not _IDENTIFIER_PATTERN.fullmatch(resource_type):
        raise ImproperlyConfigured("Typ referencji zasobu ma nieprawidłowy format.")
    existing = _handlers.get(resource_type)
    if existing is not None and existing is not handler:
        raise ImproperlyConfigured(
            f"Typ referencji zasobu jest już zarejestrowany: {resource_type}"
        )
    _handlers[resource_type] = handler


def record_resource_references(
    *,
    context: TenantContext,
    resource_type: str,
    owner_type: str,
    owner_id: UUID,
    resource_ids: tuple[UUID, ...],
) -> tuple[UUID, ...]:
    _require_matching_context(context)
    return _handler(resource_type).record(
        context=context,
        owner_type=owner_type,
        owner_id=owner_id,
        resource_ids=_normalized_ids(resource_ids),
    )


def list_resource_reference_ids(
    *,
    context: TenantContext,
    resource_type: str,
    owner_type: str,
    owner_id: UUID,
) -> tuple[UUID, ...]:
    _require_matching_context(context)
    return _handler(resource_type).list_ids(
        context=context,
        owner_type=owner_type,
        owner_id=owner_id,
    )


def _handler(resource_type: str) -> ResourceReferenceHandler:
    try:
        return _handlers[resource_type]
    except KeyError as error:
        raise ImproperlyConfigured(
            f"Brak aktywnego handlera referencji zasobu: {resource_type}"
        ) from error


def _normalized_ids(resource_ids: tuple[UUID, ...]) -> tuple[UUID, ...]:
    return tuple(sorted(set(resource_ids), key=str))


def _require_matching_context(context: TenantContext) -> None:
    if require_tenant_context() != context:
        raise ResourceReferenceRejected
