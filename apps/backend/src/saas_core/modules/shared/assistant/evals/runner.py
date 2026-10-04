"""Runs the scenarios against one candidate model (A3; ADR-033 „Jakość i koszty”).

The same prompt and the same tools a customer's conversation gets — of every
registered command exposed to the assistant, the ones of the areas the
conversation has touched (`topics.select`), widened by the model on demand —
with purpose `eval`: the deployment's budget pays, no company. Tools are not
executed: a read answers with the scenario's fixture and a write with the
scenario's outcome, so a run touches no tenant data and its grading is
deterministic. An answer with a verb form that has a gender is sent back once,
as in a conversation (`style`). The report says how often the model did the
right thing, what a message costs and how long a call takes; the owner picks
the model on those numbers.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import median
from typing import Any

from saas_core.modules.core.organizations.api import (
    UnknownCommand,
    command,
    command_for_tool,
    registered_commands,
)
from saas_core.modules.shared.model_port.api import (
    Message,
    ModelContext,
    ModelError,
    ModelRequest,
    ToolSpec,
    complete,
)

from .. import style, topics
from ..permissions import TASK
from ..prompts import PROMPT_ID, PROMPT_VERSION, system_prompt
from ..turns import cached_tail
from .scenarios import READS, SCENARIOS, Scenario

#: Model calls one scenario may take: read, propose, report — and one spare.
MAX_STEPS = 4
# A sentence that says the change is in place. Statements only: „to get it
# changed, ask…” and „nie zmieniono” are not claims.
_DONE_CLAIM = re.compile(
    r"\b(gotowe(?! (?:do|są|jest|będ))|zrobione|zmieniono|zaktualizowano|ustawiono|dodano|"
    r"został[ao]? (zmienion|zaktualizowan|ustawion|dodan)\w*|nazywa się teraz|"
    r"done|is now|has been (changed|updated|renamed|set|added)|"
    r"was (changed|updated|renamed)|i(?:'ve| have) (changed|updated|renamed|set|added))\b",
    re.IGNORECASE,
)
_NOT = re.compile(
    r"(\b(nie|not|no|bez|without|cannot|unable|never)\b|n't\b|\bcouldn)", re.IGNORECASE
)
_TECHNICAL = re.compile(r"(_v\d+\b|@\d+\b|\b[a-z]+\.[a-z_]+\.[a-z_]+\b|[{}])")
# The language of an answer by its commonest words: an English answer may
# quote a Polish service name, and a short Polish one may have no diacritics.
_WORDS = re.compile(r"[a-ząćęłńóśźż']+", re.IGNORECASE)
_POLISH_WORDS = frozenset([
    "nie",
    "się",
    "jest",
    "na",
    "do",
    "że",
    "i",
    "w",
    "z",
    "to",
    "czy",
    "jaka",
    "jaką",
    "masz",
    "mam",
    "firmy",
    "nazwa",
    "nazwę",
    "gotowe",
    "zmieniono",
    "została",
    "został",
    "usługi",
    "usługę",
    "proszę",
    "podaj",
    "możesz",
    "można",
    "mogę",
    "ale",
    "oraz",
])
_ENGLISH_WORDS = frozenset([
    "the",
    "is",
    "are",
    "your",
    "you",
    "and",
    "to",
    "of",
    "has",
    "have",
    "been",
    "what",
    "which",
    "it",
    "this",
    "that",
    "can",
    "cannot",
    "do",
    "not",
    "was",
    "will",
    "would",
    "please",
    "should",
    "i",
    "a",
    "an",
    "in",
    "for",
    "with",
])
_MARKDOWN = re.compile(r"(\*\*|__|^#{1,6} |^\|.*\|$|`)", re.MULTILINE)


@dataclass(slots=True)
class ScenarioResult:
    key: str
    passed: bool = False
    failed: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    answer: str = ""
    steps: int = 0
    cost_usd_micros: int = 0
    latencies_ms: list[int] = field(default_factory=list)
    invalid_arguments: int = 0
    error: str = ""


def assistant_tools() -> tuple[ToolSpec, ...]:
    """Every command an owner's assistant is offered."""
    return tuple(
        ToolSpec(
            name=spec.tool_name, description=spec.model_description, input_schema=spec.input_schema
        )
        for spec in registered_commands()
        if "assistant" in spec.exposure
    )


def scenario_keys(kind: str) -> list[str]:
    return [scenario.key for scenario in _suite(kind)[0]]


def _suite(kind: str) -> tuple[Sequence[Any], Any, tuple[ToolSpec, ...], str]:
    """A kind of conversation's scenarios, how one is run, the tools its model
    gets and its prompt."""
    if kind == "setup":
        # Here, not at the top: the setup runner shares this module's grading.
        from ..prompts import SETUP_PROMPT_ID, SETUP_PROMPT_VERSION  # noqa: PLC0415
        from .setup_runner import run_setup_scenario, setup_tools  # noqa: PLC0415
        from .setup_scenarios import SETUP_SCENARIOS  # noqa: PLC0415

        return (
            SETUP_SCENARIOS,
            run_setup_scenario,
            setup_tools(),
            f"{SETUP_PROMPT_ID}@{SETUP_PROMPT_VERSION}",
        )
    return SCENARIOS, run_scenario, assistant_tools(), f"{PROMPT_ID}@{PROMPT_VERSION}"


def run_eval(
    *, model: str, max_usd: float, keys: Sequence[str] | None = None, kind: str = "operate"
) -> dict[str, Any]:
    scenarios, run, tools, prompt = _suite(kind)
    budget = int(max_usd * 1_000_000)
    spent = 0
    results: list[ScenarioResult] = []
    for scenario in scenarios:
        if keys and scenario.key not in keys:
            continue
        if spent >= budget:
            break
        result = run(scenario, model=model, tools=tools)
        spent += result.cost_usd_micros
        results.append(result)
    latencies = sorted(ms for result in results for ms in result.latencies_ms)
    return {
        "model": model,
        "kind": kind,
        "prompt": prompt,
        "tools": len(tools),
        "scenarios": len(results),
        "passed": sum(result.passed for result in results),
        "skipped_for_budget": len([s for s in scenarios if not keys or s.key in keys])
        - len(results),
        "cost_usd": round(spent / 1_000_000, 4),
        "cost_per_message_usd": round(spent / 1_000_000 / max(len(results), 1), 4),
        "model_calls": len(latencies),
        "latency_ms_p50": int(median(latencies)) if latencies else None,
        "latency_ms_p95": latencies[int(len(latencies) * 0.95) - 1] if latencies else None,
        "invalid_arguments": sum(result.invalid_arguments for result in results),
        "errors": sorted({result.error for result in results if result.error}),
        "results": [
            {
                "key": result.key,
                "passed": result.passed,
                "failed": result.failed,
                "calls": result.calls,
                "steps": result.steps,
                "cost_usd_micros": result.cost_usd_micros,
                "answer": result.answer,
                "error": result.error,
            }
            for result in results
        ],
    }


def run_scenario(scenario: Scenario, *, model: str, tools: tuple[ToolSpec, ...]) -> ScenarioResult:
    result = ScenarioResult(key=scenario.key)
    context = ModelContext(
        organization_id=None,
        actor_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        purpose="eval",
    )
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    system = Message(role="system", content=system_prompt(language=scenario.language), cache=True)
    messages: list[Message] = [Message(role="user", content=f"[{stamp}] {scenario.message}")]
    available = [
        {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
        for tool in tools
    ]
    # As in a conversation: the tools of the areas the person's words and the
    # model's calls have touched so far.
    events: list[Sequence[str]] = [topics.said(scenario.message)]
    arguments: dict[str, list[Mapping[str, Any]]] = {}
    # An answer held back for its words, with the panel's note: sent once and
    # never kept — as the conversation's own check does (`turns._rewritten`).
    held: tuple[Message, ...] = ()
    first = ""
    for _ in range(MAX_STEPS):
        result.steps += 1
        request = ModelRequest(
            task=TASK,
            messages=(system, *cached_tail(messages), *held),
            prompt_id=PROMPT_ID,
            prompt_version=PROMPT_VERSION,
            context=context,
            data_class="personal",
            tools=tuple(
                ToolSpec(
                    name=tool["name"],
                    description=tool["description"],
                    input_schema=tool["input_schema"],
                )
                for tool in topics.select(available, events)
            ),
            cache_tools=True,
            model=model,
        )
        try:
            response = complete(request)
        except ModelError as error:
            if error.kind != "tool_args_invalid" or error.response is None:
                result.error = f"{error.kind}:{error.code}"
                break
            # As in a conversation: the answer goes back with what was wrong.
            result.invalid_arguments += 1
            response = error.response
            result.cost_usd_micros += response.cost_usd_micros or 0
            result.latencies_ms.append(response.latency_ms)
            messages.append(response.as_message())
            for call in response.tool_calls:
                messages.append(
                    _tool(call.id, {"status": "refused", "error": {"code": "command_args_invalid"}})
                )
            continue
        result.cost_usd_micros += response.cost_usd_micros or 0
        result.latencies_ms.append(response.latency_ms)
        if held:
            # Written again: taken when it is an answer in words, else the
            # first one stands.
            again = "" if response.tool_calls else (response.text or "").strip()
            result.answer = again or first
            break
        if not response.tool_calls:
            first = response.text or ""
            form = style.gendered(first)
            if form:
                held = style.rewrite_messages(response, form)
                continue
            result.answer = first
            break
        messages.append(response.as_message())
        for call in response.tool_calls:
            events.append(topics.called(call.name, call.arguments_json))
            if call.name == topics.MORE_TOOLS:
                messages.append(
                    _tool(
                        call.id,
                        {"status": "done", "output": topics.opened(call.arguments_json, available)},
                    )
                )
                continue
            try:
                spec = command_for_tool(call.name)
            except UnknownCommand:
                messages.append(_tool(call.id, {"status": "refused", "error": {"code": "unknown"}}))
                continue
            result.calls.append(spec.key)
            arguments.setdefault(spec.key, []).append(call.arguments or {})
            if spec.risk == "read":
                output = scenario.reads.get(spec.key, READS.get(spec.key, {}))
                messages.append(_tool(call.id, {"status": "done", "output": output}))
            elif scenario.write_result.get("status") == "done":
                # As a command answers: with what it saved.
                saved = {k: v for k, v in (call.arguments or {}).items() if v is not None}
                messages.append(_tool(call.id, {"status": "done", "output": saved}))
            else:
                messages.append(_tool(call.id, scenario.write_result))
    result.failed = grade(scenario, result, arguments)
    result.passed = not result.failed and not result.error
    return result


def _tool(call_id: str, content: Mapping[str, Any]) -> Message:
    return Message(
        role="tool", tool_call_id=call_id, content=json.dumps(content, ensure_ascii=False)
    )


def grade(
    scenario: Scenario,
    result: ScenarioResult,
    arguments: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[str]:
    """The checks a scenario failed, by name."""
    failed: list[str] = []
    for key, expected in scenario.calls.items():
        made = arguments.get(key)
        if not made:
            failed.append(f"not_called:{key}")
            continue
        # Several calls of one command count together: two changes may be
        # one call or two.
        merged: dict[str, Any] = {}
        for call in made:
            merged.update({name: value for name, value in call.items() if value is not None})
        for name, value in expected.items():
            if merged.get(name) != value:
                failed.append(f"wrong_argument:{key}.{name}")
    if scenario.no_writes:
        writes = [key for key in result.calls if _is_write(key)]
        if writes:
            failed.append(f"wrote:{writes[0]}")
    answer = result.answer
    if not answer and not result.error:
        failed.append("no_answer")
    if scenario.asks and "?" not in answer:
        failed.append("did_not_ask")
    if scenario.no_done_claim and _claims_done(answer):
        failed.append("claimed_done")
    for text in scenario.says:
        if text.lower() not in answer.lower():
            failed.append(f"did_not_say:{text}")
    for text in scenario.never_says:
        if text.lower() in answer.lower():
            failed.append(f"said:{text}")
    if answer:
        if _TECHNICAL.search(answer):
            failed.append("technical_names")
        if _MARKDOWN.search(answer):
            failed.append("markdown")
        if style.gendered(answer):
            failed.append("gendered_verb")
        if _language(answer) not in {scenario.language, ""}:
            failed.append("wrong_language")
    return failed


def _is_write(key: str) -> bool:
    return command(key).risk != "read"


def _language(answer: str) -> str:
    """`pl`, `en`, or empty when the answer does not say."""
    words = [word.lower() for word in _WORDS.findall(answer)]
    polish = sum(word in _POLISH_WORDS for word in words)
    english = sum(word in _ENGLISH_WORDS for word in words)
    if polish == english:
        return ""
    return "pl" if polish > english else "en"


def _claims_done(answer: str) -> bool:
    """A sentence that says the change was made, without a negation in it."""
    for sentence in re.split(r"[.!?\n]+", answer):
        if _DONE_CLAIM.search(sentence) and not _NOT.search(sentence):
            return True
    return False
