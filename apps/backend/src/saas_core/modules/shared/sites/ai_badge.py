"""Whether public pages show the visible AI marking (ADR-059 pkt 7)."""

from __future__ import annotations

from .models import AiBadgeSwitch


def badge_visible() -> bool:
    # No rows means visible; only an explicit operator `--off` hides the badge.
    return (
        AiBadgeSwitch.objects.order_by("-created_at", "-id")
        .values_list("visible", flat=True)
        .first()
        is not False
    )
