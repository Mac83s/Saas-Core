"""How many stored messages and exports are past their retention and still
hold data — a read-only count, company by company.

    manage.py notification_retention_report

Zero is the healthy answer: the hourly sweep (`tasks.scrub_expired`) clears
them. A number that stays above zero after an hour means the sweep is not
running. Prints counts only, never an address or a text.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from saas_core.modules.shared.billing.tenant_scope import (
    billing_organization_ids,
    billing_tenant_scope,
)
from saas_core.modules.shared.notifications.models import DataExport, ExportStatus
from saas_core.modules.shared.notifications.services import expired_unscrubbed


class Command(BaseCommand):
    help = "Wiadomości i eksporty po terminie retencji, które wciąż trzymają dane (tylko liczy)."

    def handle(self, *args: Any, **options: Any) -> None:
        messages = exports = companies = 0
        oldest = None
        for organization_id in billing_organization_ids():
            with billing_tenant_scope(organization_id):
                due = expired_unscrubbed(organization_id)
                count = due.count()
                stale = (
                    DataExport.all_objects.filter(
                        organization_id=organization_id, expires_at__lte=timezone.now()
                    )
                    .exclude(status=ExportStatus.EXPIRED)
                    .count()
                )
                if count:
                    first = due.order_by("retention_expires_at").values_list(
                        "retention_expires_at", flat=True
                    )[0]
                    oldest = first if oldest is None else min(oldest, first)
                if count or stale:
                    companies += 1
                messages += count
                exports += stale
        self.stdout.write(
            f"Po terminie i nieoczyszczone: wiadomości {messages}, eksporty {exports}, "
            f"firmy {companies}"
            + (f"; najstarszy termin {oldest:%Y-%m-%d}" if oldest else "")
            + ". Niczego nie zmieniono."
        )
