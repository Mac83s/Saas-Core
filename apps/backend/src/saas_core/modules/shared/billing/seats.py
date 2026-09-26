"""The plan's number of panel accounts, for Core's invitation check (ADR-058 §9)."""

from .decisions import decide_quota

TEAM_MEMBERS_MAX = "team_members.max"


def team_members_limit() -> int | None:
    """None when the organization's snapshot names no limit: like `pages.max`,
    a plan version older than the limit refuses nobody."""
    decision = decide_quota(TEAM_MEMBERS_MAX)
    return decision.value if decision.available else None
