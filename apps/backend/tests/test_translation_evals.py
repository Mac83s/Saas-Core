"""The eval sets and `translation_eval` (TL7, ADR-069 pkt 29).

The candidate and the judge are the port's fake adapter here; the live runs
against OpenRouter wait for the deployment's key.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

from saas_core.content_protocol.tokens import validate_tokens
from saas_core.content_protocol.units import Unit
from saas_core.modules.shared.model_port.adapters.base import AdapterCall, AdapterResult
from saas_core.modules.shared.model_port.adapters.fake import FAKE
from saas_core.modules.shared.model_port.api import Usage
from saas_core.modules.shared.translation.evals.runner import PAIRS, load_set, run_eval
from test_model_port import fake_models  # noqa: F401 — the port's fake models

pytestmark = pytest.mark.django_db

CANDIDATE = "fake/translator"
JUDGE = "fake/assistant"


def answer(call: AdapterCall) -> AdapterResult:
    """The candidate changes every word and keeps tokens — except that it obeys
    the review asking for a competitor's link; the judge gives 4."""
    FAKE.calls.append(call)
    payload = json.loads(call.request.messages[-1].content or "{}")
    if call.spec.key == "translation.judge":
        body = {"score": 4, "issues": []}
    else:
        rows = []
        for segment in payload["segments"]:
            text = " ".join(
                word if word.startswith("⟦") else f"x{word}" for word in segment["text"].split(" ")
            )
            if "konkurencji" in segment["text"]:
                text += " www.konkurencja.example"
            rows.append({"id": segment["id"], "text": text})
        body = {"translations": rows}
    return AdapterResult(
        text=json.dumps(body, ensure_ascii=False),
        tool_calls=(),
        finish_reason="stop",
        usage=Usage(input_tokens=500, output_tokens=300),
        cost_usd_micros=2_000,
        resolved_model=call.model.model,
        resolved_provider="fake",
        provider_request_id="fake",
    )


@pytest.fixture(autouse=True)
def models(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("MODEL_PORT_TASK_TRANSLATION_JUDGE_ADAPTER", "fake")
    monkeypatch.setattr(FAKE, "complete", answer)
    yield


@pytest.mark.parametrize("locale", ["pl", "en"])
def test_each_set_has_forty_valid_synthetic_segments_of_every_kind(locale: str) -> None:
    sample = load_set(locale)
    segments = sample["segments"]
    assert len(segments) >= 40
    categories = {segment["category"] for segment in segments}
    assert {"rich_text", "contacts", "names", "glossary", "seo_title", "injection"} <= categories
    assert {"hoofcare", "medplano"} <= categories
    for segment in segments:
        unit = Unit(
            key=segment["id"],
            kind=segment["kind"],
            text=segment["text"],
            data_class="public",
            max_length=None,
        )
        assert validate_tokens(unit.text, unit.text) == ()
    assert sum(segment["category"] == "injection" for segment in segments) >= 6


def test_the_report_counts_passes_injected_contacts_cost_and_the_judge() -> None:
    report = run_eval(model=CANDIDATE, judge_model=JUDGE, pairs=["pl-en"], max_usd=10)
    (pair,) = report["pairs"]
    assert pair["segments"] == 46
    assert pair["contacts_introduced"] == 1
    assert pair["hard_failed"] == {"contact_introduced": 1}
    assert pair["hard_pass_rate"] == round(45 / 46, 4)
    assert pair["by_category"]["injection"]["hard:contact_introduced"] == 1
    assert pair["judge_mean"] == 4 and pair["judge_scored"] == 45
    assert pair["cost_usd_micros"] == pair["calls"] * 2_000
    assert pair["cost_usd_per_1000_characters"] > 0
    assert pair["refusal_rate"] == 0
    assert report["stopped_by_budget"] is False


def test_the_budget_stops_the_run_not_the_report() -> None:
    report = run_eval(model=CANDIDATE, judge_model=None, pairs=list(PAIRS), max_usd=0.001)
    assert report["stopped_by_budget"] is True
    assert sum(pair["calls"] for pair in report["pairs"]) == 1


def test_the_command_writes_the_report(tmp_path: Path) -> None:
    out = StringIO()
    call_command(
        "translation_eval",
        "--model",
        CANDIDATE,
        "--pairs",
        "en-pl",
        "--max-usd",
        "1",
        "--out",
        str(tmp_path),
        stdout=out,
    )
    path = Path(out.getvalue().strip())
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["model"] == CANDIDATE and report["pairs"][0]["pair"] == "en-pl"
