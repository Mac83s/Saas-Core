"""What each model can do through each adapter, and what it costs (ADR-068 pkt 3).

A model becomes selectable for a task only after a live probe confirmed this
row (`model_port_probe`, report in `docs/evals/model-port/`) and only when it
has every capability the task needs. A person changes this table in a commit;
nothing changes it at run time. Prices serve estimates and ceilings — the cost
recorded is the provider's own when the response carries it.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Capabilities a row may claim. A request using one the task's model lacks is
#: refused before any call (`capability_not_supported`); the port never
#: emulates a forced tool or a schema.
CAPABILITIES = frozenset({
    "tools",
    "tool_choice_required",
    "tool_choice_named",
    "parallel_tool_calls_off",
    "strict_tools",
    "json_schema",
    "json_mode",
    "json_schema_with_tools",
    "reasoning_effort",
    "temperature",
    "zdr",
    "prompt_cache",
    "continuation",
})


@dataclass(frozen=True, slots=True)
class ModelProfile:
    adapter: str
    model: str
    capabilities: frozenset[str]
    #: Parameters the adapter must not send to this model.
    forbidden_parameters: frozenset[str]
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    context_window: int
    max_output_tokens: int
    #: The date of the live probe that confirmed this row; None — not selectable.
    probed: str | None = None
    #: Dated snapshots the provider may answer with for this model.
    dated_variants: frozenset[str] = frozenset()

    def estimate_usd_micros(self, *, input_tokens: int, output_tokens: int) -> int:
        return int(
            input_tokens * self.input_usd_per_mtok + output_tokens * self.output_usd_per_mtok
        )


#: The plan's candidates (TL7). Capabilities and prices follow the claude-api
#: skill as of 2026-09-25 and still need the live probe through OpenRouter, so
#: none is selectable yet: Opus 5.5 and Sonnet 5.5 take neither temperature nor
#: top_p and refuse a forced tool_choice; Haiku 4.5 has no effort parameter.
MODELS: dict[tuple[str, str], ModelProfile] = {
    ("openrouter", "anthropic/claude-opus-5.5"): ModelProfile(
        adapter="openrouter",
        model="anthropic/claude-opus-5.5",
        capabilities=frozenset({
            "tools",
            "strict_tools",
            "json_schema",
            "json_schema_with_tools",
            "reasoning_effort",
            "zdr",
            "prompt_cache",
            "continuation",
        }),
        forbidden_parameters=frozenset({"temperature", "top_p"}),
        input_usd_per_mtok=4.0,
        output_usd_per_mtok=20.0,
        context_window=200_000,
        max_output_tokens=32_000,
    ),
    ("openrouter", "anthropic/claude-sonnet-5.5"): ModelProfile(
        adapter="openrouter",
        model="anthropic/claude-sonnet-5.5",
        capabilities=frozenset({
            "tools",
            "strict_tools",
            "json_schema",
            "json_schema_with_tools",
            "reasoning_effort",
            "zdr",
            "prompt_cache",
            "continuation",
        }),
        forbidden_parameters=frozenset({"temperature", "top_p"}),
        input_usd_per_mtok=2.0,
        output_usd_per_mtok=10.0,
        context_window=200_000,
        max_output_tokens=32_000,
    ),
    ("openrouter", "anthropic/claude-haiku-4.5"): ModelProfile(
        adapter="openrouter",
        model="anthropic/claude-haiku-4.5",
        capabilities=frozenset({
            "tools",
            "tool_choice_required",
            "tool_choice_named",
            "strict_tools",
            "json_schema",
            "json_schema_with_tools",
            "temperature",
            "zdr",
            "prompt_cache",
        }),
        forbidden_parameters=frozenset({"reasoning"}),
        input_usd_per_mtok=1.0,
        output_usd_per_mtok=5.0,
        context_window=200_000,
        max_output_tokens=16_000,
    ),
}


def model_profile(adapter: str, model: str) -> ModelProfile | None:
    return MODELS.get((adapter, model))


def register_model(profile: ModelProfile) -> None:
    """A row added in code — the fake adapter's models in tests, a product's own."""
    unknown = profile.capabilities - CAPABILITIES
    if unknown:
        raise ValueError(f"Nieznane możliwości modelu: {sorted(unknown)}")
    MODELS[(profile.adapter, profile.model)] = profile
