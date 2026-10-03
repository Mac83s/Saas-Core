"""Evale modelu rozmowy asystenta przed ruchem klientów (ADR-033, ADR-076, A3).

Syntetyczne scenariusze po polsku i angielsku przechodzą przez ten sam prompt
i te same narzędzia co rozmowa klienta, z celem `eval`: płaci budżet
wdrożenia, żadna firma. Narzędzia nie są wykonywane — odczyt odpowiada danymi
scenariusza, zapis jego wynikiem — więc ocena jest deterministyczna. Raport
JSON trafia do `docs/evals/assistant/`; model wybiera właściciel na liczbach.

    python manage.py assistant_eval --model anthropic/claude-sonnet-5.5 --max-usd 1.2
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from ...evals.runner import run_eval
from ...evals.scenarios import SCENARIOS


class Command(BaseCommand):
    help = "Evale modelu rozmowy asystenta na syntetycznych scenariuszach; raport JSON."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--model", required=True, help="Model kandydat z macierzy portu.")
        parser.add_argument("--max-usd", type=float, required=True)
        parser.add_argument(
            "--scenarios", default="", help="Klucze po przecinku; puste: wszystkie."
        )
        parser.add_argument("--out", default="docs/evals/assistant")

    def handle(self, *_args: Any, **options: Any) -> None:
        keys = [key.strip() for key in options["scenarios"].split(",") if key.strip()]
        unknown = sorted(set(keys) - {scenario.key for scenario in SCENARIOS})
        if unknown:
            raise CommandError(f"Nieznane scenariusze: {', '.join(unknown)}.")
        if options["max_usd"] <= 0:
            raise CommandError("--max-usd musi być dodatni.")
        report = run_eval(model=options["model"], max_usd=options["max_usd"], keys=keys or None)
        report["at"] = datetime.now(UTC).isoformat()
        directory = Path(options["out"])
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (
            options["model"].replace("/", "_")
            + "-"
            + datetime.now(UTC).strftime("%Y%m%d")
            + ".json"
        )
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.stdout.write(
            f"{report['passed']}/{report['scenarios']} scenariuszy, "
            f"USD {report['cost_usd']} ({report['cost_per_message_usd']} na wiadomość), "
            f"p95 {report['latency_ms_p95']} ms → {path}"
        )
