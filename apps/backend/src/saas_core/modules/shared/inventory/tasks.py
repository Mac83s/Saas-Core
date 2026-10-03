from __future__ import annotations

from celery import shared_task


@shared_task  # type: ignore[untyped-decorator]
def notify_low_stock() -> int:
    """Every hour: the daily low-stock notice of each company that wants it."""
    from .alerts import notify_low_stock as notify  # noqa: PLC0415

    return notify()
