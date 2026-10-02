"""Evale modelu tłumaczeń przed ruchem klientów (ADR-069 pkt 29, TL7).

Syntetyczne zestawy pl→en, pl→de, pl→es, pl→ru i en→pl przechodzą tę samą
drogę co zlecenie klienta (maski, paczki, prompt `translation.v1`, kontrola
twarda i miękka), z celem `eval`: płaci budżet wdrożenia, żadna firma.
Sędzia z innej rodziny modeli ocenia każdy wynik 1–5. Raport JSON trafia do
`docs/evals/translation/`; model domyślny wybiera właściciel na liczbach.

    python manage.py translation_eval --model anthropic/claude-sonnet-5.5 \\
        --judge-model google/gemini-2.5-flash --max-usd 5
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from ...evals.runner import PAIRS, run_eval


class Command(BaseCommand):
    help = "Evale modelu tłumaczeń na syntetycznych zestawach; raport JSON."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--model", required=True, help="Model kandydat z macierzy portu.")
        parser.add_argument("--judge-model", help="Sędzia z innej rodziny modeli.")
        parser.add_argument("--pairs", default=",".join(PAIRS), help="Np. pl-en,pl-de.")
        parser.add_argument("--max-usd", type=float, required=True)
        parser.add_argument("--out", default="docs/evals/translation")

    def handle(self, *_args: Any, **options: Any) -> None:
        pairs = [pair.strip() for pair in options["pairs"].split(",") if pair.strip()]
        unknown = sorted(set(pairs) - set(PAIRS))
        if unknown:
            raise CommandError(f"Nieznane pary: {', '.join(unknown)}.")
        if options["max_usd"] <= 0:
            raise CommandError("--max-usd musi być dodatni.")
        report = run_eval(
            model=options["model"],
            judge_model=options["judge_model"],
            pairs=pairs,
            max_usd=options["max_usd"],
        )
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
        self.stdout.write(str(path))
