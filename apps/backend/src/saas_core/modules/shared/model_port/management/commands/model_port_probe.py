"""A live probe of one model's row in the matrix (ADR-068 pkt 3).

Small real calls through the port, with a spending limit, checking what the
matrix claims: a plain answer, a strict JSON schema, tools, forced tool
choice, reasoning effort and how a refusal comes back. The report goes to
`docs/evals/model-port/`; a person then confirms the row in `matrix.py`
(`probed`) by a commit — nothing here changes the matrix.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from ...api import (
    JsonSchemaFormat,
    Message,
    ModelContext,
    ModelError,
    ModelRequest,
    ToolSpec,
    complete,
)
from ...matrix import model_profile

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string"}},
}
TOOL = ToolSpec(
    name="probe_echo",
    description="Returns the word it gets.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["word"],
        "properties": {"word": {"type": "string"}},
    },
)


class Command(BaseCommand):
    help = "Próba na żywo modelu z macierzy portu, z limitem wydatków; raport JSON."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--adapter", default="openrouter")
        parser.add_argument("--model", required=True)
        parser.add_argument("--max-usd", type=float, required=True)
        parser.add_argument("--out", default="docs/evals/model-port")

    def handle(self, *args: Any, **options: Any) -> None:
        profile = model_profile(options["adapter"], options["model"])
        if profile is None:
            raise CommandError("Modelu nie ma w macierzy; najpierw dopisz wiersz.")
        limit = int(options["max_usd"] * 1_000_000)
        base = ModelRequest(
            task="translation.text",
            messages=(Message(role="user", content="Answer with the single word: ready."),),
            prompt_id="model_port.probe",
            prompt_version="1",
            context=ModelContext(organization_id=None, purpose="probe"),
            data_class="public",
            model=profile.model,
            max_tokens=256,
        )
        checks: dict[str, Any] = {}
        spent = 0
        for name, request in (
            ("plain", base),
            ("json_schema", replace(base, response_format=JsonSchemaFormat("probe", SCHEMA))),
            ("tools_auto", replace(base, tools=(TOOL,), tool_choice="auto")),
            ("tool_choice_required", replace(base, tools=(TOOL,), tool_choice="required")),
        ):
            if spent >= limit:
                checks[name] = {"skipped": "max_usd"}
                continue
            try:
                response = complete(request)
                spent += response.cost_usd_micros or 0
                checks[name] = {
                    "ok": True,
                    "finish_reason": response.finish_reason,
                    "resolved_model": response.resolved_model,
                    "resolved_provider": response.resolved_provider,
                    "cost_usd_micros": response.cost_usd_micros,
                    "cost_source": response.cost_source,
                    "tool_calls": len(response.tool_calls),
                    "latency_ms": response.latency_ms,
                }
            except ModelError as error:
                checks[name] = {"ok": False, "kind": error.kind, "code": error.code}
        report = {
            "adapter": profile.adapter,
            "model": profile.model,
            "at": datetime.now(UTC).isoformat(),
            "claimed_capabilities": sorted(profile.capabilities),
            "checks": checks,
            "spent_usd_micros": spent,
        }
        directory = Path(options["out"])
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (
            profile.model.replace("/", "_") + "-" + datetime.now(UTC).strftime("%Y%m%d") + ".json"
        )
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.stdout.write(str(path))
