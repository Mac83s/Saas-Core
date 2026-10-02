"""Public extension API of the Organizations module."""

from .canonical import canonical_json, canonical_json_hash
from .command_registry import (
    CommandSpec,
    Effect,
    Preview,
    UnknownCommand,
    command,
    command_for_tool,
    command_tools,
    register_command,
    registered_commands,
)
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
    "CommandSpec",
    "DomainEvent",
    "DomainEventDeliveryError",
    "DomainEventHandler",
    "Effect",
    "InvitationAcceptedHandler",
    "Preview",
    "ResourceReferenceConflict",
    "ResourceReferenceHandler",
    "ResourceReferenceRejected",
    "SeatLimit",
    "SeatLimitReached",
    "UnknownCommand",
    "canonical_json",
    "canonical_json_hash",
    "command",
    "command_for_tool",
    "command_tools",
    "copy_resource_references",
    "dispatch_domain_event",
    "list_resource_reference_ids",
    "record_resource_references",
    "register_command",
    "register_domain_event_handler",
    "register_invitation_accepted",
    "register_resource_reference_handler",
    "register_seat_limit",
    "registered_commands",
]
