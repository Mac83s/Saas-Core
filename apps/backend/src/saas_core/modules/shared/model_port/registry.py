"""The task registry: a named way of using a model, configured in one place (ADR-068 pkt 2).

A caller names a task; its pool, adapter, model, limits and capabilities live
here. Defaults are in code, overridable per field by an environment variable
`MODEL_PORT_TASK_<TASK>_<FIELD>` until the settings registry (settings plan,
phase 1) takes over. Core modules and products add their own tasks with
`register_task` from `AppConfig.ready`.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import replace
from datetime import timedelta

from .types import TaskSpec

logger = logging.getLogger(__name__)

POOLS = frozenset({"translation", "assistant"})

_TASKS: dict[str, TaskSpec] = {}
_KEY = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")

#: The tasks every deployment has from day one. Their model is the owner's
#: choice on the evals: Claude Sonnet 5.5 for translation (TL7, answer 53 of
#: 03.10) and for the assistant (answer 59a of 03.10, `docs/evals/assistant/`).
#: Claude Haiku 4.5 stays the assistant's fallback: a probed row an operator
#: sets with `MODEL_PORT_TASK_ASSISTANT_<TASK>_MODEL` when Sonnet is unavailable.
DEFAULT_TASKS = (
    TaskSpec(
        key="translation.text",
        pool="translation",
        adapter="openrouter",
        model="anthropic/claude-sonnet-5.5",
        timeout_seconds=150,
        max_tokens_rule=(2.5, 1024, 16_384),
        defaults={"reasoning_effort": "low"},
        capabilities=frozenset({"json_schema"}),
        max_data_class="public_personal",
        required_context=frozenset({"organization_id"}),
        resend_unknown=True,
        admission_ttl=timedelta(minutes=10),
        purposes=frozenset({"customer", "platform", "eval", "probe"}),
    ),
    TaskSpec(
        key="assistant.conversation",
        pool="assistant",
        adapter="openrouter",
        model="anthropic/claude-sonnet-5.5",
        timeout_seconds=18,
        max_tokens_rule=(0.0, 1536, 1536),
        capabilities=frozenset({"tools", "zdr"}),
        max_data_class="personal",
        required_context=frozenset({"organization_id", "actor_id", "conversation_id"}),
    ),
    TaskSpec(
        key="assistant.extract_profile",
        pool="assistant",
        adapter="openrouter",
        model="anthropic/claude-sonnet-5.5",
        timeout_seconds=15,
        max_tokens_rule=(0.0, 1024, 1024),
        capabilities=frozenset({"json_schema", "zdr"}),
        max_data_class="personal",
        required_context=frozenset({"organization_id", "actor_id"}),
    ),
)


def register_task(spec: TaskSpec) -> None:
    """A task from a module's `AppConfig.ready`; the same spec twice is no change."""
    if _KEY.fullmatch(spec.key) is None:
        raise ValueError(f"Klucz zadania {spec.key!r} ma postać <moduł>.<zadanie>.")
    if spec.pool not in POOLS:
        raise ValueError(f"Zadanie {spec.key} wskazuje nieznaną pulę {spec.pool!r}.")
    existing = _TASKS.get(spec.key)
    if existing is not None and existing != spec:
        raise ValueError(f"Zadanie {spec.key} jest już zarejestrowane inaczej.")
    _TASKS[spec.key] = spec


def registered_tasks() -> tuple[str, ...]:
    return tuple(sorted(_TASKS))


def task_spec(key: str, *, platform: bool = True) -> TaskSpec | None:
    """The task with its overrides applied, or None for an unknown key.

    `platform`: the operator's model from the platform settings comes first
    (TL22), then the environment, then the code; False skips the settings —
    the startup checks run before the database is there."""
    spec = _TASKS.get(key)
    if spec is None:
        return None
    spec = _overridden(spec)
    return _platform_model(spec) if platform else spec


def _platform_model(spec: TaskSpec) -> TaskSpec:
    from saas_core.modules.core.organizations.platform_settings import read_platform_setting

    from .settings_spec import TASK_MODEL_SETTINGS, selectable_models

    setting_key = TASK_MODEL_SETTINGS.get(spec.key)
    if setting_key is None:
        return spec
    chosen = read_platform_setting(setting_key)
    # Only an operator's choice overrides: the code default is the spec's own,
    # and the environment's override has already been applied.
    if chosen.source != "platform":
        return spec
    if chosen.value not in selectable_models(spec.key):
        logger.warning(
            "model_port_platform_model_ignored",
            extra={"task": spec.key, "model": str(chosen.value)},
        )
        return spec
    return replace(spec, model=str(chosen.value))


def _overridden(spec: TaskSpec) -> TaskSpec:
    prefix = "MODEL_PORT_TASK_" + spec.key.replace(".", "_").upper() + "_"
    changes: dict[str, object] = {}
    for name, convert in (
        ("model", str),
        ("adapter", str),
        ("timeout_seconds", float),
        ("enabled", _boolean),
        ("daily_cap_usd", float),
    ):
        raw = os.environ.get(prefix + name.upper())
        if raw is not None and raw.strip() != "":
            changes[name] = convert(raw.strip())
    return replace(spec, **changes) if changes else spec  # type: ignore[arg-type]


def _boolean(value: str) -> bool:
    return value.lower() not in {"0", "false", "no", "off"}


for _spec in DEFAULT_TASKS:
    register_task(_spec)
