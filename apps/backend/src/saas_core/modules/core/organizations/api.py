"""Public extension API of the Organizations module."""

from .events import (
    DomainEvent,
    DomainEventDeliveryError,
    DomainEventHandler,
    dispatch_domain_event,
    register_domain_event_handler,
)
from .joining import (
    InvitationAcceptedHandler,
    SeatLimit,
    SeatLimitReached,
    register_invitation_accepted,
    register_seat_limit,
)
from .references import (
    ResourceReferenceConflict,
    ResourceReferenceHandler,
    ResourceReferenceRejected,
    copy_resource_references,
    list_resource_reference_ids,
    record_resource_references,
    register_resource_reference_handler,
)

__all__ = [
    "DomainEvent",
    "DomainEventDeliveryError",
    "DomainEventHandler",
    "InvitationAcceptedHandler",
    "ResourceReferenceConflict",
    "ResourceReferenceHandler",
    "ResourceReferenceRejected",
    "SeatLimit",
    "SeatLimitReached",
    "copy_resource_references",
    "dispatch_domain_event",
    "list_resource_reference_ids",
    "record_resource_references",
    "register_domain_event_handler",
    "register_invitation_accepted",
    "register_resource_reference_handler",
    "register_seat_limit",
]
