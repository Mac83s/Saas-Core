"""What Booking adds to its tenants' catalogue search documents (ADR-064).

Service names are the words a visitor searches by ("strzyżenie psa", "korekcja
racic") and a company rarely repeats them in its own name. Profiles cannot
import Booking — Booking depends on Profiles — so Booking registers here.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from saas_core.modules.shared.profiles.api import catalog_changed

from .models import Service


def service_names(organization_id: UUID) -> list[str]:
    """Active services; runs with the tenant already set by the indexer."""
    return list(
        Service.all_objects.filter(organization_id=organization_id, active=True).values_list(
            "name", flat=True
        )
    )


def service_changed(sender: Any, instance: Service, **_kwargs: Any) -> None:
    catalog_changed(instance.organization_id)
