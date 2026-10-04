from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.checks import Error, register


@register()
def assistant_configuration(app_configs: Any, **kwargs: Any) -> list[Any]:
    """Proof accounts are for local stacks: their conversations skip every
    daily ceiling of the model port. The dev VPS runs as `local` too, so the
    name of the environment protects nothing — a stack served over https that
    names one has to fail its deploy (as `model_port.E003` does)."""
    if settings.ASSISTANT_PROOF_ACCOUNTS and settings.PUBLIC_SITE_SCHEME == "https":
        return [
            Error(
                "ASSISTANT_PROOF_ACCOUNTS jest ustawione na stacku serwowanym przez https. "
                "Konta dowodowe asystenta są tylko dla lokalnych stacków na http — usuń tę "
                "zmienną.",
                id="assistant.E001",
            )
        ]
    return []
