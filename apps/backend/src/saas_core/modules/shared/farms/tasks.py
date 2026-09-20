"""Co rejestr mówi hodowcy sam z siebie (ADR-051 pkt 7).

Firma wpisuje zwierzęta do cudzego rejestru — nowe sztuki i poprawki stanu.
Nic z tego nie jest kasowane ani zatwierdzane za hodowcę: wiersze dostają
znacznik „do przejrzenia", a ten przebieg raz na dobę mówi o nich osobom, które
mogą się tym zająć.

Powiadomienie jest jedno na gospodarstwo, nie na sztukę, i kluczem jest moment
ostatniego znacznika: import czterystu krów jedną transakcją to jedna wiadomość,
a kolejny przebieg bez nowych sztuk nie mówi nic.
"""

from __future__ import annotations

from celery import shared_task
from django.db import transaction
from django.db.models import Count, Max

from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.models import Membership, MembershipStatus
from saas_core.modules.shared.notifications.api import notify_in_app

from .models import Animal, FarmShare
from .services import FARMS_MANAGE

NOTIFICATION_KIND = "farms.herd_review"


@shared_task(  # type: ignore[untyped-decorator]
    name="saas_core.modules.shared.farms.tasks.notify_pending_reviews"
)
def notify_pending_reviews() -> int:
    """Ile wiadomości powstało. Wołalna wprost, więc test nie potrzebuje Celery."""
    created = 0
    # `FarmShare` nie ma klucza do organizacji i nie podlega RLS, więc to
    # jedyna lista rejestrów, jaką zadanie dostaje bez kontekstu tenanta.
    registries = FarmShare.objects.values_list("registry_organization_id", flat=True).distinct()
    for organization_id in registries:
        with transaction.atomic():
            # Zanim cokolwiek przeczyta: polityka na tabelach zwierząt i
            # członkostw wpuszcza tylko po ustawieniu tenanta.
            set_local_organization_id(organization_id)
            pending = (
                Animal.all_objects.filter(
                    organization_id=organization_id, review_requested_at__isnull=False
                )
                .values("farm_id", "farm__name")
                .annotate(count=Count("id"), latest=Max("review_requested_at"))
            )
            if not pending:
                continue
            recipients = [
                membership
                for membership in Membership.objects.select_related("role").filter(
                    organization_id=organization_id, status=MembershipStatus.ACTIVE
                )
                if FARMS_MANAGE in (membership.role.permissions or [])
            ]
            for row in pending:
                key = f"farms-review:{row['farm_id']}:{row['latest'].isoformat()}"
                payload = {
                    "farm_id": str(row["farm_id"]),
                    "farm_name": row["farm__name"],
                    "count": row["count"],
                }
                for membership in recipients:
                    created += notify_in_app(
                        organization_id=organization_id,
                        user_id=membership.user_id,
                        kind=NOTIFICATION_KIND,
                        payload=payload,
                        idempotency_key=key,
                    )
    return created
