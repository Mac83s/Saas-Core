from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.checks import Error, Warning, register

from . import test_double
from .budgets import current_budgets, problems
from .registry import registered_tasks, task_spec

WEB_TIMEOUT_MARGIN = 2.0


@register()
def model_port_configuration(app_configs: Any, **kwargs: Any) -> list[Any]:
    """Ceilings that would let the key trip first, and web calls longer than
    a graceful restart allows, refuse the start (ADR-068 pkt 5 and 7)."""
    found: list[Any] = [
        Error(message, id="model_port.E001") for message in problems(current_budgets())
    ]
    graceful = float(settings.GUNICORN_GRACEFUL_TIMEOUT)
    if graceful <= WEB_TIMEOUT_MARGIN:
        found.append(
            Error(
                "GUNICORN_GRACEFUL_TIMEOUT nie zostawia czasu na wywołanie modelu z żądania.",
                id="model_port.E002",
            )
        )
    if test_double.refused():
        # The dev VPS is named `local`, so the name protects nothing: a wrong
        # line in a `.env` has to fail the deploy, not translate a customer's
        # site with the stand-in.
        found.append(
            Error(
                "MODEL_PORT_TEST_DOUBLE jest włączone na stacku serwowanym przez https. "
                "Atrapa tłumaczeń jest tylko dla testów przeglądarkowych na http — "
                "usuń tę zmienną.",
                id="model_port.E003",
            )
        )
    for key in registered_tasks():
        spec = task_spec(key, platform=False)
        if (
            spec is not None
            and spec.model
            and spec.adapter == "fake"
            and settings.APP_ENV not in {"test", "local"}
        ):
            found.append(
                Warning(f"Zadanie {key} wskazuje atrapę poza testami.", id="model_port.W001")
            )
    return found
