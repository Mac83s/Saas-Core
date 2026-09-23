"""Reading the organization's history of changes (owner and admin only).

Writing is `audit.record_audit`; this module only decides who may read the
rows and how they are shown: the channel as one of a few words, the before and
after of a change apart from the rest of the metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .audit import PANEL_PRINCIPAL
from .authorization import authorize
from .models import OrganizationAuditEntry
from .permissions import SETTINGS_MANAGE

PAGE_SIZE_MAX = 100
#: Keys the history screen shows in their own columns, not among the details.
_OWN_COLUMNS = frozenset({"changes", "fields"})
#: `shared.notifications` names its key principal so; core only recognises it.
_API_KEY_PRINCIPAL = "api_key"


@dataclass(frozen=True, slots=True)
class HistoryPage:
    total: int
    entries: list[OrganizationAuditEntry]
    actions: list[str]


def list_history(*, page: int, page_size: int, action: str = "") -> HistoryPage:
    context = authorize(SETTINGS_MANAGE)
    rows = OrganizationAuditEntry.objects.filter(organization_id=context.organization_id)
    actions = sorted(set(rows.values_list("action", flat=True)))
    if action:
        rows = rows.filter(action=action)
    start = (page - 1) * page_size
    return HistoryPage(
        total=rows.count(),
        entries=list(
            rows.select_related("actor_user").order_by("-occurred_at", "-id")[
                start : start + page_size
            ]
        ),
        actions=actions,
    )


def channel(entry: OrganizationAuditEntry) -> str | None:
    """Panel, an API key, or the system acting for the organization.

    Rows written before 2026-09-23 carry no channel and answer None.
    """
    kind = entry.channel
    if not kind:
        return None
    if kind == PANEL_PRINCIPAL:
        return "panel"
    if kind == _API_KEY_PRINCIPAL:
        return "api_key"
    return "system"


def history_item(entry: OrganizationAuditEntry) -> dict[str, Any]:
    actor = entry.actor_user
    metadata = entry.metadata or {}
    return {
        "id": entry.id,
        "occurred_at": entry.occurred_at,
        "action": entry.action,
        "actor": None
        if actor is None
        else {
            "name": " ".join(filter(None, [actor.first_name, actor.last_name])) or actor.email,
            "email": actor.email,
        },
        "channel": channel(entry),
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "changes": metadata.get("changes") or {},
        "changed_fields": metadata.get("fields") or [],
        "details": {key: value for key, value in metadata.items() if key not in _OWN_COLUMNS},
    }
