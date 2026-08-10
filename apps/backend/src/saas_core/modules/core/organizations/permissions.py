from typing import Final

ORGANIZATION_READ: Final = "organization.read"
MEMBERS_READ: Final = "organization.members.read"
MEMBERS_MANAGE_LIMITED: Final = "organization.members.manage_limited"
MEMBERS_MANAGE: Final = "organization.members.manage"
SETTINGS_MANAGE: Final = "organization.settings.manage"
BILLING_MANAGE: Final = "organization.billing.manage"
OWNERSHIP_TRANSFER: Final = "organization.ownership.transfer"
ORGANIZATION_ARCHIVE: Final = "organization.archive"

SYSTEM_ROLE_PERMISSIONS: Final[dict[str, tuple[str, ...]]] = {
    "viewer": (ORGANIZATION_READ,),
    "staff": (ORGANIZATION_READ, MEMBERS_READ),
    "manager": (ORGANIZATION_READ, MEMBERS_READ, MEMBERS_MANAGE_LIMITED),
    "admin": (
        ORGANIZATION_READ,
        MEMBERS_READ,
        MEMBERS_MANAGE_LIMITED,
        MEMBERS_MANAGE,
        SETTINGS_MANAGE,
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
    ),
}
