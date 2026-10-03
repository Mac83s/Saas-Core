"""Reading the organization's history of changes (owner and admin only).

Writing is `audit.record_audit`; this module only decides who may read the
rows and how they are shown: the channel as one of a few words, the before and
after of a change apart from the rest of the metadata.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from .audit import PANEL_PRINCIPAL
from .authorization import authorize
from .models import OrganizationAuditAction, OrganizationAuditEntry
from .permissions import SETTINGS_MANAGE

PAGE_SIZE_MAX = 100
#: Keys the history screen shows in their own columns, not among the details.
_OWN_COLUMNS = frozenset({"changes", "fields"})
#: `shared.notifications` names its key principal so; core only recognises it.
_API_KEY_PRINCIPAL = "api_key"


@dataclass(frozen=True, slots=True)
class HistoryTarget:
    """What a history row is about, for people (UX-055): „Dodano gospodarstwo:
    Ferma Pod Lasem”, not four identical rows. `at` is the object's own time
    (a visit's start); `href` is where the panel shows it, when it does."""

    label: str
    href: str = ""
    at: datetime | None = None


#: Names the objects of one target type that still exist: (organization, ids)
#: -> what each is called. A module registers one for its own types; a row
#: whose object is gone, or whose type nobody names, stays without a name.
#: Never a customer's name or contact: the history is read by whoever manages
#: settings, not by whoever may see every visit.
TargetNamer = Callable[[UUID, Sequence[UUID]], Mapping[UUID, HistoryTarget]]

_target_namers: dict[str, TargetNamer] = {}


def register_history_target(target_type: str, namer: TargetNamer) -> None:
    _target_namers[target_type] = namer


def _name_targets(
    organization_id: UUID, entries: Sequence[OrganizationAuditEntry]
) -> dict[tuple[str, UUID], HistoryTarget]:
    wanted: dict[str, set[UUID]] = defaultdict(set)
    for entry in entries:
        if entry.target_id is not None and entry.target_type in _target_namers:
            wanted[entry.target_type].add(entry.target_id)
    return {
        (target_type, target_id): target
        for target_type, ids in wanted.items()
        for target_id, target in _target_namers[target_type](organization_id, sorted(ids)).items()
    }


@dataclass(frozen=True, slots=True)
class HistoryPage:
    total: int
    entries: list[OrganizationAuditEntry]
    actions: list[str]
    targets: dict[tuple[str, UUID], HistoryTarget] = field(default_factory=dict)


def list_history(
    *, page: int, page_size: int, action: str = "", group: str = "", key: str = ""
) -> HistoryPage:
    context = authorize(SETTINGS_MANAGE)
    rows = OrganizationAuditEntry.objects.filter(organization_id=context.organization_id)
    actions = sorted(set(rows.values_list("action", flat=True)))
    if action:
        rows = rows.filter(action=action)
    # A settings change names its group in the target and its fields in the
    # metadata (ADR-078 pkt 9); a key is its group and its last segment.
    if key:
        group, _, field = key.rpartition(".")
        rows = rows.filter(metadata__fields__contains=[field])
    if group:
        rows = rows.filter(action=OrganizationAuditAction.SETTINGS_CHANGED, target_type=group)
    start = (page - 1) * page_size
    entries = list(
        rows.select_related("actor_user").order_by("-occurred_at", "-id")[start : start + page_size]
    )
    return HistoryPage(
        total=rows.count(),
        entries=entries,
        actions=actions,
        targets=_name_targets(context.organization_id, entries),
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


def acting(entry: OrganizationAuditEntry) -> dict[str, Any] | None:
    """Through what the person's membership acted, when not by the person's own
    hand (ADR-076 §6); `channel` stays the principal."""
    if not entry.acting_via:
        return None
    return {
        "via": entry.acting_via,
        "ref": entry.acting_ref,
        "trigger": entry.acting_trigger or None,
    }


def history_item(
    entry: OrganizationAuditEntry,
    targets: Mapping[tuple[str, UUID], HistoryTarget] | None = None,
) -> dict[str, Any]:
    actor = entry.actor_user
    metadata = entry.metadata or {}
    target = (
        (targets or {}).get((entry.target_type, entry.target_id))
        if entry.target_id is not None
        else None
    )
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
        "acting": acting(entry),
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "target": None
        if target is None
        else {"label": target.label, "href": target.href, "at": target.at},
        "changes": metadata.get("changes") or {},
        "changed_fields": metadata.get("fields") or [],
        "details": {key: value for key, value in metadata.items() if key not in _OWN_COLUMNS},
    }
