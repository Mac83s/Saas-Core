"""Public extension API of the Organizations module."""

from .references import (
    ResourceReferenceConflict,
    ResourceReferenceHandler,
    ResourceReferenceRejected,
    list_resource_reference_ids,
    record_resource_references,
    register_resource_reference_handler,
)

__all__ = [
    "ResourceReferenceConflict",
    "ResourceReferenceHandler",
    "ResourceReferenceRejected",
    "list_resource_reference_ids",
    "record_resource_references",
    "register_resource_reference_handler",
]
