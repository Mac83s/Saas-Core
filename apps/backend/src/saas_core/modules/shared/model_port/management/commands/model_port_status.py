"""What the port can do now, what it has spent, and lifting a block (ADR-068)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from ...api import budget_state, task_status
from ...registry import registered_tasks, task_spec
from ...state import unblock
from ...types import ModelContext

security = logging.getLogger("saas_core.security")


class Command(BaseCommand):
    help = (
        "Stan portu modeli: zadania, blokady i wydatki wobec sufitów; --unblock zdejmuje blokadę."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--unblock", metavar="TASK")
        parser.add_argument("--operator")
        parser.add_argument("--reason")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["unblock"]:
            spec = task_spec(options["unblock"])
            if spec is None:
                raise CommandError("Nieznane zadanie.")
            if not options["operator"] or not (options["reason"] or "").strip():
                raise CommandError("Podaj --operator i --reason.")
            unblock(spec.key, spec.model, spec.adapter)
            security.warning(
                "model_port_unblocked",
                extra={"task": spec.key, "operator": options["operator"]},
            )
            self.stdout.write(f"Zdjęto blokady zadania {spec.key}.")
            return
        context = ModelContext(organization_id=None, purpose="probe")
        report = {
            key: {
                "status": {
                    **asdict(task_status(key)),
                    "capabilities": sorted(task_status(key).capabilities),
                },
                "budgets": [asdict(level) for level in budget_state(key, context).levels],
            }
            for key in registered_tasks()
        }
        self.stdout.write(json.dumps(report, default=str, indent=2, ensure_ascii=False))
