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
    #: Probed for evals only: not offered as a task's model in the platform
    #: settings — customer content to it is the owner's decision (TL22).
    evaluation_only: bool = False

    def estimate_usd_micros(self, *, input_tokens: int, output_tokens: int) -> int:
        return int(
            input_tokens * self.input_usd_per_mtok + output_tokens * self.output_usd_per_mtok
        )


@dataclass(frozen=True, slots=True)
class Processor:
    """One chain a company's content travels, link by link — what the
    platform's privacy documents name („Podmiot przetwarzający”)."""

    #: The intermediary the platform sends the request to, by its adapter:
    #: `openrouter` — OpenRouter, Inc.
    adapter: str
    #: Who runs the model, as the intermediary names the host in a request's
    #: provider preferences: `google-vertex/europe` — Google Cloud, Vertex AI,
    #: a European region.
    host: str
    #: Whose model, as the intermediary names it: `anthropic/…` — Anthropic.
    model: str


#: The processors the platform's privacy documents name for companies'
#: content (the owner's answers of 04.10.2026; `docs/architecture/model-port.md`,
#: „Podmiot przetwarzający”): through OpenRouter, run by Google Cloud (Vertex
#: AI, European region), Claude Sonnet 5.5 and — as the fallback — Claude Haiku
#: 4.5 by Anthropic. Nothing else is sent a company's content: the platform's
#: setting of a task's model refuses another model (`settings_spec.py`), the
#: call itself is refused when `.env` or code names one (`service._gates`), and
#: the host is the one the provider pin names
#: (`model_port.privacy.claude_provider`). Another model or another host is
#: another entry in the documents first, then a row here.
LISTED_PROCESSORS = (
    Processor("openrouter", "google-vertex/europe", "anthropic/claude-sonnet-5.5"),
    Processor("openrouter", "google-vertex/europe", "anthropic/claude-haiku-4.5"),
)
#: The one of them the tasks that send a company's content default to; a test
#: holds them to it.
LISTED_PROCESSOR = ("openrouter", "anthropic/claude-sonnet-5.5")
#: The adapter that never leaves the process (tests, the stand-in translator):
#: nobody processes what it is given, so the list does not apply to it.
IN_PROCESS_ADAPTER = "fake"

#: The plan's candidates (TL7). Capabilities and prices follow the claude-api
#: skill as of 2026-09-25 and OpenRouter's model list; each row is confirmed by
#: its live probe of 2026-10-02 (`docs/evals/model-port/`). Opus 5.5 and Sonnet
#: 5.5 take neither temperature nor top_p and refuse a forced tool_choice;
#: Haiku 4.5 has no effort parameter. A task still has no model until a person
#: picks its default on the evals (`docs/evals/translation/`).
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
        probed="2026-10-02",
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
        probed="2026-10-02",
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
        probed="2026-10-02",
    ),
    # The plan's Gemini Flash class candidate: the newest Flash on OpenRouter's
    # list of 2026-10-03, price from that list. No zdr or prompt_cache claimed.
    ("openrouter", "google/gemini-3.8-flash"): ModelProfile(
        adapter="openrouter",
        model="google/gemini-3.8-flash",
        capabilities=frozenset({
            "tools",
            "tool_choice_required",
            "json_schema",
            "json_schema_with_tools",
            "reasoning_effort",
            "temperature",
        }),
        forbidden_parameters=frozenset(),
        input_usd_per_mtok=0.75,
        output_usd_per_mtok=3.75,
        context_window=1_048_576,
        max_output_tokens=65_536,
        probed="2026-10-02",
    ),
    # DeepSeek V4 Pro (answer 53 of 03.10: a test beside Sonnet 5.5). Both
    # snapshots OpenRouter lists under the name; the probe of 2026-10-03
    # confirmed plain, JSON schema, tools and forced tools on both (answered by
    # third-party hosts: StreamLake, NextBit, Wafer, Ionstream, Relace). Test
    # data only: another processor
    # jurisdiction, so production use is the owner's decision (RODO, provider
    # routing, MODEL_PORT_PROCESSOR_LISTED).
    ("openrouter", "deepseek/deepseek-v4-pro"): ModelProfile(
        adapter="openrouter",
        model="deepseek/deepseek-v4-pro",
        capabilities=frozenset({
            "tools",
            "tool_choice_required",
            "json_schema",
            "json_schema_with_tools",
            "reasoning_effort",
            "temperature",
        }),
        forbidden_parameters=frozenset(),
        input_usd_per_mtok=0.2088,
        output_usd_per_mtok=0.4176,
        context_window=1_024_000,
        max_output_tokens=384_000,
        probed="2026-10-03",
        evaluation_only=True,
    ),
    ("openrouter", "deepseek/deepseek-v4-pro-0813"): ModelProfile(
        adapter="openrouter",
        model="deepseek/deepseek-v4-pro-0813",
        capabilities=frozenset({
            "tools",
            "tool_choice_required",
            "json_schema",
            "json_schema_with_tools",
            "reasoning_effort",
            "temperature",
        }),
        forbidden_parameters=frozenset(),
        input_usd_per_mtok=0.66,
        output_usd_per_mtok=1.98,
        context_window=1_048_576,
        max_output_tokens=393_216,
        probed="2026-10-03",
        evaluation_only=True,
    ),
}


def processor_listed(adapter: str, model: str) -> bool:
    """Whether a company's content may go to this model: the documents name
    a chain that serves it, or nobody would process it (the in-process
    adapter)."""
    return adapter == IN_PROCESS_ADAPTER or bool(listed_hosts(adapter, model))


def listed_hosts(adapter: str, model: str) -> tuple[str, ...]:
    """The hosts the documents name for this model through this intermediary."""
    return tuple(
        chain.host
        for chain in LISTED_PROCESSORS
        if (chain.adapter, chain.model) == (adapter, model)
    )


def model_profile(adapter: str, model: str) -> ModelProfile | None:
    return MODELS.get((adapter, model))


def register_model(profile: ModelProfile) -> None:
    """A row added in code — the fake adapter's models in tests, a product's own."""
    unknown = profile.capabilities - CAPABILITIES
    if unknown:
        raise ValueError(f"Nieznane możliwości modelu: {sorted(unknown)}")
    MODELS[(profile.adapter, profile.model)] = profile
