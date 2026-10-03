"""A stand-in translator for browser tests (TL15d).

`fake/echo`, one model of the fake adapter, answers a translation call without
a script: every segment back with the target language in front, tokens and
markers untouched. A company gets it only when two things hold: the stack says
`MODEL_PORT_TEST_DOUBLE` by name, and the company has a row in
`TestDoubleCompany`. Everybody else keeps the real model, its price and its
ceilings, and a test that dies half-way leaves only its own company behind.

The switch is an explicit setting, default off, and never follows `APP_ENV`:
the dev VPS runs as `local`. On a stack served over https the switch is an
error at start and the stand-in stays off (`refused`). The list is fixture
state in its own table — not a setting, so no operator can reach it from the
panel.
`manage.py translation_e2e_fixture on|off` writes it; no model, price or key
is ever written.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from uuid import UUID

from django.conf import settings

from .adapters.base import AdapterCall, AdapterResult
from .matrix import ModelProfile
from .types import TaskSpec, Usage

ECHO_MODEL = "fake/echo"
#: The one task the stand-in answers.
ECHO_TASK = "translation.text"


def refused() -> bool:
    """Asked for on a stack served over https — one that answers the internet.

    The start check stops such a stack (`model_port.E003`); `enabled` keeps the
    stand-in off as well, for a process that got past the check."""
    return bool(settings.MODEL_PORT_TEST_DOUBLE) and settings.PUBLIC_SITE_SCHEME == "https"


def enabled() -> bool:
    return bool(settings.MODEL_PORT_TEST_DOUBLE) and not refused()


def echo_profile() -> ModelProfile:
    return ModelProfile(
        adapter="fake",
        model=ECHO_MODEL,
        capabilities=frozenset({"json_schema", "json_mode", "zdr"}),
        forbidden_parameters=frozenset(),
        input_usd_per_mtok=0.0,
        output_usd_per_mtok=0.0,
        context_window=1_000_000,
        max_output_tokens=64_000,
        # Nothing to probe: it never leaves the process.
        probed="2026-10-03",
        evaluation_only=True,
    )


def uses_stand_in(organization_id: UUID) -> bool:
    """A row alone is not enough: with the switch off nobody is on it."""
    if not enabled():
        return False
    from .models import TestDoubleCompany

    return TestDoubleCompany.objects.filter(pk=organization_id).exists()


def routed(spec: TaskSpec, organization_id: UUID | None) -> TaskSpec:
    """The task as this company calls it: the stand-in for a listed company
    where the switch is on, the task itself for everybody else."""
    if spec.key != ECHO_TASK or organization_id is None:
        return spec
    if not uses_stand_in(organization_id):
        return spec
    return replace(spec, adapter="fake", model=ECHO_MODEL)


def echo(call: AdapterCall) -> AdapterResult:
    """Every segment back, marked with the language it was to be in."""
    payload: dict[str, Any] = json.loads(call.request.messages[-1].content or "{}")
    target = str(payload.get("target_language") or "")
    rows = [
        {"id": segment["id"], "text": f"[{target}] {segment['text']}"}
        for segment in payload.get("segments", [])
    ]
    text = json.dumps({"translations": rows}, ensure_ascii=False)
    return AdapterResult(
        text=text,
        tool_calls=(),
        finish_reason="stop",
        usage=Usage(
            input_tokens=len(call.request.messages[-1].content or "") // 4 + 1,
            output_tokens=len(text) // 4 + 1,
        ),
        cost_usd_micros=0,
        resolved_model=ECHO_MODEL,
        resolved_provider="fake",
        provider_request_id="fake-echo",
    )
