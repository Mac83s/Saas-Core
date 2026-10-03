"""Runs the setup scenarios against one candidate model (A3-2).

The same prompt and the same three tools a setup conversation gets, with
purpose `eval`. The tools answer as the real ones do — the notes go through
the same rules of origin, the status is the configurator's own answer — over
a profile kept in memory and a synthetic account, so a run touches no company
and its grading is deterministic.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from typing import Any

from rest_framework.exceptions import ValidationError

from saas_core.http.exceptions import problem_errors
from saas_core.modules.core.organizations.api import registered_commands
from saas_core.modules.shared.model_port.api import (
    Message,
    ModelContext,
    ModelError,
    ModelRequest,
    ToolSpec,
    complete,
)

from .. import setup
from ..configurator import PRESETS, SETUP, WRITES, configure, fold, said_values
from ..permissions import TASK
from ..profile_schema import empty_profile, validate_profile
from ..prompts import SETUP_PROMPT_ID, SETUP_PROMPT_VERSION, system_prompt
from .runner import (
    _GENDERED,
    _MARKDOWN,
    _TECHNICAL,
    ScenarioResult,
    _claims_done,
    _language,
    _tool,
)
from .setup_scenarios import ACCOUNT, SETUP_REF, SetupScenario

#: Model calls one message may take: status, note, status again, the answer —
#: and one spare.
MAX_STEPS = 5
_DECLINED = {"status": "declined", "error": {"code": "consent_declined", "errors": []}}
#: What an owner writes in their own words; a key (a kind of booking, a
#: category) is the owner's when they chose its label, which no text shows.
_FREE_TEXT = (
    "company.name",
    "company.activity",
    "company.city",
    "company.address",
    "company.phone",
    "company.email",
    "card.*",
    "places.*.name",
    "places.*.address",
    "people.*.name",
    "offers.*.name",
)


def setup_tools() -> tuple[ToolSpec, ...]:
    return tuple(
        ToolSpec(
            name=tool["name"], description=tool["description"], input_schema=tool["input_schema"]
        )
        for tool in setup.TOOLS
    )


def run_setup_scenario(
    scenario: SetupScenario, *, model: str, tools: tuple[ToolSpec, ...]
) -> ScenarioResult:
    result = ScenarioResult(key=scenario.key)
    context = ModelContext(
        organization_id=None,
        actor_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        purpose="eval",
    )
    start = copy.deepcopy(dict(scenario.profile)) or empty_profile()
    state = _State(document=copy.deepcopy(start), scenario=scenario)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    messages: list[Message] = [
        Message(
            role="system", content=system_prompt(language=scenario.language, setup=True), cache=True
        )
    ]
    spoken: list[str] = []
    for text in scenario.messages:
        state.owner_words += f"\n{text}"
        messages.append(Message(role="user", content=f"[{stamp}] {text}"))
        result.answer = ""
        for _ in range(MAX_STEPS):
            result.steps += 1
            request = ModelRequest(
                task=TASK,
                messages=tuple(messages),
                prompt_id=SETUP_PROMPT_ID,
                prompt_version=SETUP_PROMPT_VERSION,
                context=context,
                data_class="personal",
                tools=tools,
                cache_tools=True,
                model=model,
            )
            try:
                response = complete(request)
            except ModelError as error:
                if error.kind != "tool_args_invalid" or error.response is None:
                    result.error = f"{error.kind}:{error.code}"
                    break
                result.invalid_arguments += 1
                response = error.response
                result.cost_usd_micros += response.cost_usd_micros or 0
                result.latencies_ms.append(response.latency_ms)
                messages.append(response.as_message())
                messages.extend(
                    _tool(call.id, {"status": "refused", "error": {"code": "command_args_invalid"}})
                    for call in response.tool_calls
                )
                continue
            result.cost_usd_micros += response.cost_usd_micros or 0
            result.latencies_ms.append(response.latency_ms)
            messages.append(response.as_message())
            spoken.append(response.text or "")
            if not response.tool_calls:
                result.answer = response.text or ""
                break
            for call in response.tool_calls:
                result.calls.append(call.name)
                messages.append(_tool(call.id, state.answer(call.name, call.arguments or {})))
        if result.error:
            break
    result.failed = grade_setup(
        scenario, result, start, state.document, state.owner_words, spoken="\n".join(spoken)
    )
    result.passed = not result.failed and not result.error
    return result


class _State:
    """The profile and the owner's words as the conversation goes."""

    def __init__(self, *, document: dict[str, Any], scenario: SetupScenario) -> None:
        self.document = document
        self.scenario = scenario
        self.owner_words = ""
        self.version = 1 if len(document) > 1 else 0

    def answer(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """What the tool answers, as in a conversation."""
        if name == setup.PROFILE_NOTE:
            notes = arguments.get("notes", [])
            try:
                changed, proposals = setup.with_notes(self.document, notes, self.owner_words)
                validate_profile(changed)
            except ValidationError as error:
                return {
                    "status": "refused",
                    "error": {"code": "invalid", "errors": list(problem_errors(error))},
                }
            self.document = changed
            self.version += 1
            return {"status": "done", "output": setup.noted(notes, proposals, self.version)}
        # The commands the registry has today: a step it lacks is told to
        # the model as waiting, as in a conversation.
        commands = frozenset(WRITES) & {spec.key for spec in registered_commands()}
        account = {key: read for key, read in ACCOUNT.items() if key not in self.scenario.without}
        if self.scenario.ready and PRESETS in account:
            account[PRESETS] = {
                "presets": [
                    {**preset, "readiness": "ready"}
                    if preset["id"] in self.scenario.ready
                    else preset
                    for preset in account[PRESETS]["presets"]
                ]
            }
        if self.scenario.drafts and SETUP in account:
            account[SETUP] = {
                **account[SETUP],
                "services": [
                    {
                        "id": f"draft-{number}",
                        "name": name,
                        "time_model": "range",
                        "range_unit": "night",
                        "duration_minutes": None,
                        "staff_ids": [],
                        "location_ids": [],
                        "resource_ids": [],
                        "group_ids": [],
                        "active": False,
                        "draft": True,
                        "origin_ref": SETUP_REF,
                    }
                    for number, name in enumerate(self.scenario.drafts, start=1)
                ],
            }
        answer = configure(self.document, account, commands, setup_refs=[SETUP_REF])
        if name == setup.SETUP_STATUS:
            return {
                "status": "done",
                "output": setup.described(self.document, answer, self.scenario.language),
            }
        if name != setup.SETUP_APPLY:
            return {"status": "refused", "error": {"code": "unknown_tool", "errors": []}}
        if self.scenario.apply_result != "done":
            return _DECLINED
        return {
            "status": "done",
            "output": {
                "steps": [
                    {"step": step["ref"], "status": "done", "error": None}
                    for step in answer["plan"]
                ]
            },
        }


def grade_setup(
    scenario: SetupScenario,
    result: ScenarioResult,
    start: Mapping[str, Any],
    document: Mapping[str, Any],
    owner_words: str,
    *,
    spoken: str = "",
) -> list[str]:
    """The checks a scenario failed, by name. `spoken` is everything the model
    wrote in the conversation, the words beside its tool calls included."""
    failed: list[str] = []
    foreign = sorted({name for name in result.calls if name not in setup.TOOL_NAMES})
    failed += [f"unknown_tool:{name}" for name in foreign]
    if setup.SETUP_STATUS not in result.calls:
        # What to ask is the configurator's to say, not the model's.
        failed.append("no_status")
    before = dict(said_values(start))
    values = dict(said_values(document))
    owned = {
        field: node["value"]
        for field, node in values.items()
        if node["origin"] == "owner" and node["confirmed"]
    }
    for field, value in owned.items():
        if (
            any(fnmatchcase(field, pattern) for pattern in _FREE_TEXT)
            and before.get(field, {}).get("value") != value
            and not _written(field, value, owner_words)
        ):
            # Nobody wrote it and it was not there to agree to: a guess.
            failed.append(f"guess_marked_owner:{field}")
    for pattern, expected in scenario.owner_said.items():
        found = [value for field, value in owned.items() if fnmatchcase(field, pattern)]
        if not any(_same(value, expected) for value in found):
            failed.append(f"not_noted:{pattern}")
    failed += [
        f"noted_as_owner:{pattern}"
        for pattern in scenario.not_owner
        if any(fnmatchcase(field, pattern) for field in owned)
    ]
    failed += [
        f"noted:{pattern}"
        for pattern in scenario.absent
        if any(fnmatchcase(field, pattern) for field in values)
    ]
    applied = setup.SETUP_APPLY in result.calls
    if scenario.applies is True and not applied:
        failed.append("did_not_apply")
    if scenario.applies is False and applied:
        failed.append("applied")
    answer = result.answer
    if not answer and not result.error:
        failed.append("no_answer")
    if scenario.asks and "?" not in answer:
        failed.append("did_not_ask")
    if scenario.no_done_claim and _claims_done(answer):
        failed.append("claimed_done")
    failed += [
        f"did_not_say:{text}" for text in scenario.says if text.lower() not in answer.lower()
    ]
    everything = f"{spoken}\n{answer}".lower()
    failed += [
        f"never_said:{text}"
        for text in scenario.says_anytime
        if not any(variant in everything for variant in text.lower().split("|"))
    ]
    failed += [
        f"said:{text}"
        for text in (*scenario.never_says, *sorted(setup.TOOL_NAMES))
        if text.lower() in answer.lower()
    ]
    if answer:
        if _TECHNICAL.search(answer):
            failed.append("technical_names")
        if _MARKDOWN.search(answer):
            failed.append("markdown")
        if _GENDERED.search(answer):
            failed.append("gendered_verb")
        if _language(answer) not in {scenario.language, ""}:
            failed.append("wrong_language")
    return failed


def _written(field: str, value: Any, owner_words: str) -> bool:
    """Whether the owner's messages say this value. Contact details to the
    letter, as the tool itself checks them; other words by their stems, because
    people inflect what they say („w Olsztynie”, „z Mrągowa”)."""
    if field in ("company.phone", "company.email"):
        return setup.owner_typed(field, value, owner_words)
    written = fold(owner_words).split()
    return all(
        any(word.startswith(part[: max(3, len(part) - 2)]) for word in written)
        for part in fold(str(value)).split()
        if len(part) >= 3
    )


def _same(value: Any, expected: Any) -> bool:
    """A phone number by its digits, a text as people compare it, a price by
    its amount however it was written („450” is „450.00”)."""
    if isinstance(expected, Mapping) and isinstance(value, Mapping) and "amount" in expected:
        try:
            amounts = float(value.get("amount", "")), float(expected["amount"])
        except (TypeError, ValueError):
            return False
        return amounts[0] == amounts[1] and all(
            value.get(key) == expected[key] for key in ("currency", "per")
        )
    if isinstance(expected, list) and isinstance(value, list):
        # Seasons: each as expected in what was named of it; a name the model
        # gave it is no difference.
        return len(value) == len(expected) and all(
            isinstance(given, Mapping) and all(given.get(key) == item[key] for key in item)
            for given, item in zip(value, expected, strict=True)
        )
    if isinstance(expected, str) and expected.isdigit() and isinstance(value, str):
        return "".join(char for char in value if char.isdigit()).endswith(expected)
    if isinstance(expected, str) and isinstance(value, str):
        return fold(value) == fold(expected)
    return bool(value == expected)
