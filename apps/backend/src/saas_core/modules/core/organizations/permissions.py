from typing import Final

from django.conf import settings

ORGANIZATION_READ: Final = "organization.read"
MEMBERS_READ: Final = "organization.members.read"
MEMBERS_MANAGE_LIMITED: Final = "organization.members.manage_limited"
MEMBERS_MANAGE: Final = "organization.members.manage"
SETTINGS_MANAGE: Final = "organization.settings.manage"
BILLING_MANAGE: Final = "organization.billing.manage"
OWNERSHIP_TRANSFER: Final = "organization.ownership.transfer"
ORGANIZATION_ARCHIVE: Final = "organization.archive"

_CORE_ROLE_PERMISSIONS: Final[dict[str, tuple[str, ...]]] = {
    "viewer": (
        ORGANIZATION_READ,
        "notifications.preferences",
        "booking.appointment.read",
    ),
    "staff": (
        ORGANIZATION_READ,
        MEMBERS_READ,
        "notifications.preferences",
        "booking.appointment.read",
    ),
    "manager": (
        ORGANIZATION_READ,
        MEMBERS_READ,
        MEMBERS_MANAGE_LIMITED,
        "site.content.edit",
        "media.read",
        "media.manage",
        "notifications.preferences",
        "notifications.manage",
        "booking.appointment.read",
        "booking.appointment.manage",
        "profiles.manage",
        "seo.audit.read",
        "seo.gsc.read",
    ),
    "admin": (
        ORGANIZATION_READ,
        MEMBERS_READ,
        MEMBERS_MANAGE_LIMITED,
        MEMBERS_MANAGE,
        SETTINGS_MANAGE,
        "site.content.edit",
        "site.publish",
        "media.read",
        "media.manage",
        "notifications.preferences",
        "notifications.manage",
        "notifications.support",
        "integrations.manage",
        "booking.appointment.read",
        "booking.appointment.manage",
        "profiles.manage",
    ),
    "owner": (
        ORGANIZATION_READ,
        MEMBERS_READ,
        MEMBERS_MANAGE_LIMITED,
        MEMBERS_MANAGE,
        SETTINGS_MANAGE,
        BILLING_MANAGE,
        OWNERSHIP_TRANSFER,
        ORGANIZATION_ARCHIVE,
        "site.content.edit",
        "site.publish",
        "media.read",
        "media.manage",
        "notifications.preferences",
        "notifications.manage",
        "notifications.support",
        "integrations.manage",
        "booking.appointment.read",
        "booking.appointment.manage",
        "profiles.manage",
        "seo.audit.read",
        "seo.audit.run",
        "seo.gsc.read",
        "seo.gsc.manage",
    ),
}


#: The system roles as this deployment composes them: core's grants plus what
#: each composed module declares in its descriptor (`roleGrants`, ADR-049). The
#: database gets the module's part from that module's own migration.
SYSTEM_ROLE_PERMISSIONS: Final[dict[str, tuple[str, ...]]] = {
    role: tuple(dict.fromkeys([*permissions, *settings.MODULE_ROLE_GRANTS.get(role, ())]))
    for role, permissions in _CORE_ROLE_PERMISSIONS.items()
}
