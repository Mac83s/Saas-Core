"""The model a task uses, and which hosts may serve it, as platform settings
(TL22; answer 53 of 03.10; „karty osób” 04.10).

Class A: only the platform sets it — the „Platforma” panel, or
`platform_setting set model_port.tasks.translation_text <model> --operator …
--reason …`. The choice is one of the matrix rows a live probe confirmed that
have every capability the task needs **and** whose processor the platform's
privacy documents name (`matrix.LISTED_PROCESSORS`): the task sends companies'
content, so any other row is refused with what has to happen first. A value
that stops being such a row (removed, or chosen before the rule) is ignored
and the task's own default applies.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from saas_core.modules.core.organizations.api import (
    SettingArea,
    SettingGroup,
    SettingSpec,
)
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE

from .matrix import LISTED_PROCESSORS, MODELS, processor_listed
from .registry import DEFAULT_TASKS

TRANSLATION_TASK = "translation.text"

AI_AREA = SettingArea(
    key="ai",
    title={"pl": "AI i tłumaczenia", "en": "AI and translation"},
    description={
        "pl": "Modele zadań AI, ceny tłumaczeń i limity platformy.",
        "en": "The models of AI tasks, translation prices and the platform's limits.",
    },
    order=90,
)


def capable_models(task: str) -> tuple[str, ...]:
    """Probed rows of the task's adapter with every capability it needs —
    what the matrix could give the task, listed in the documents or not."""
    spec = next(spec for spec in DEFAULT_TASKS if spec.key == task)
    return tuple(
        profile.model
        for (adapter, _model), profile in MODELS.items()
        if adapter == spec.adapter
        and profile.probed is not None
        and spec.capabilities <= profile.capabilities
    )


def selectable_models(task: str) -> tuple[str, ...]:
    """The capable rows an operator may choose: not evals-only, and served by
    a processor the privacy documents name (`LISTED_PROCESSORS`)."""
    spec = next(spec for spec in DEFAULT_TASKS if spec.key == task)
    return tuple(
        model
        for model in capable_models(task)
        if not MODELS[(spec.adapter, model)].evaluation_only
        and processor_listed(spec.adapter, model)
    )


_TRANSLATION_DEFAULT = next(spec for spec in DEFAULT_TASKS if spec.key == TRANSLATION_TASK)
_LISTED_NAMES = (
    "Claude Sonnet 5.5 i Claude Haiku 4.5 (Anthropic), uruchamiane w Google Cloud "
    "(Vertex AI, region europejski), przez OpenRouter"
)
_UNLISTED = {
    "pl": "{model} — poza listą podmiotów przetwarzających",
    "en": "{model} — not on the list of processors",
}


def _choices(task: str) -> tuple[tuple[str, Mapping[str, str]], ...]:
    """Every capable row, so an operator sees what the matrix has; a row the
    documents do not cover says so in its name and is refused when chosen."""
    allowed = selectable_models(task)
    return tuple(
        (
            model,
            {"pl": model, "en": model}
            if model in allowed
            else {locale: words.format(model=model) for locale, words in _UNLISTED.items()},
        )
        for model in capable_models(task)
    )


def not_listed(model: str) -> tuple[str, str]:
    """The refusal of a model outside the listed set: what has to happen first."""
    return (
        f"Modelu {model} nie można wybrać: dokumenty prywatności platformy nie wymieniają "
        "podmiotu, który przetwarzałby wtedy treść firm. Najpierw dopisz go do polityki "
        "prywatności i umowy powierzenia (wpis „Podmiot przetwarzający” w "
        "docs/architecture/model-port.md), potem do listy LISTED_PROCESSORS w kodzie portu "
        f"modeli — dopiero wtedy da się go tu wybrać. Dziś na liście: {_LISTED_NAMES}.",
        "processor_not_listed",
    )


def _only_listed(
    _before: Mapping[str, Any], after: Mapping[str, Any]
) -> Mapping[str, tuple[str, str]]:
    """A task's model is one the privacy documents cover — refused at the
    change and its preview, on the key the operator was changing."""
    problems: dict[str, tuple[str, str]] = {}
    for task, key in TASK_MODEL_SETTINGS.items():
        field = key.rsplit(".", 1)[1]
        if after[field] not in selectable_models(task):
            problems[field] = not_listed(str(after[field]))
    return problems


TRANSLATION_MODEL = SettingSpec(
    key="model_port.tasks.translation_text",
    type="enum",
    default=_TRANSLATION_DEFAULT.model,
    scopes=("platform",),
    values=_choices(TRANSLATION_TASK),
    label={"pl": "Model tłumaczeń", "en": "Translation model"},
    model_description="The model the translation.text task calls through OpenRouter. It "
    "sends companies' content, so only a model whose processor the platform's privacy "
    "documents name can be chosen — today Claude Sonnet 5.5 and Claude Haiku 4.5 "
    "(Anthropic), run by Google Cloud (Vertex AI, European region), through OpenRouter. "
    "Any other probed row of the matrix (Gemini, DeepSeek, "
    "Claude Opus) is refused with processor_not_listed until its processor is added to "
    "the privacy documents and to LISTED_PROCESSORS. Changing the model changes cost and "
    "quality for every company; evals in docs/evals/translation compare the candidates.",
    help={
        "pl": "Model, który tłumaczy treści wszystkich firm. Wybrać można tylko model, "
        "którego podmiot przetwarzający jest w dokumentach prywatności platformy — dziś "
        f"{_LISTED_NAMES}. Inny model (Gemini, DeepSeek, Claude Opus) wymaga najpierw "
        "dopisania jego dostawcy do polityki prywatności i umowy powierzenia, a potem do "
        "listy w kodzie; do tego czasu wybór jest odrzucany. Koszt i jakość kandydatów: "
        "evale w docs/evals/translation.",
        "en": "The model that translates every company's content. Only a model whose "
        "processor is in the platform's privacy documents can be chosen — today Claude "
        "Sonnet 5.5 and Claude Haiku 4.5 (Anthropic), run by Google Cloud (Vertex AI, "
        "European region), through OpenRouter. Another model "
        "(Gemini, DeepSeek, Claude Opus) needs its provider added to the privacy policy "
        "and the data processing agreement first, then to the list in code; until then "
        "the choice is refused. Candidates' cost and quality: the evals in "
        "docs/evals/translation.",
    },
)

NO_TRAINING = SettingSpec(
    key="model_port.privacy.no_training_providers",
    type="bool",
    default=True,
    scopes=("platform",),
    label={
        "pl": "Tylko dostawcy, którzy nie zbierają zapytań",
        "en": "Only providers that do not collect requests",
    },
    model_description="On (the default): every request to a model is routed only to hosts "
    "that do not store prompts or train on them, and to zero-data-retention endpoints where "
    "the model has them. When no such host serves the task's model, the task fails "
    "(configuration / no_provider) — nothing is sent to another host. Off lets requests "
    "without personal data (public website content to translate) reach any host of the "
    "model. Requests of the personal data class ignore this switch: they always go the "
    "strict way.",
    help={
        "pl": "Włączone: zapytania do modeli AI trafiają wyłącznie do dostawców, którzy nie "
        "zapisują ich treści i nie uczą na niej modeli, a tam, gdzie model ma takie "
        "serwery — bez przechowywania danych. Gdy żaden taki dostawca nie obsługuje "
        "modelu, zadanie nie działa, zamiast pójść gdzie indziej. Zapytania z danymi "
        "osobowymi idą tak zawsze, także po wyłączeniu.",
        "en": "On: requests to AI models go only to providers that neither store their "
        "content nor train on it, and to zero-data-retention endpoints where the model has "
        "them. When no such provider serves the model, the task stops instead of going "
        "elsewhere. Requests with personal data always go this way, even when this is off.",
    },
)

#: The hosts OpenRouter serves Anthropic's models from: the slug a request
#: names in `provider.order` / `provider.only`, and the name its answer
#: carries in `provider` (https://openrouter.ai/api/v1/providers and
#: …/models/anthropic/claude-sonnet-5.5/endpoints, read 2026-10-04).
CLAUDE_PROVIDERS = {
    "anthropic": "Anthropic",
    "google-vertex": "Google",
    # One region of a host: the full slug, as OpenRouter's endpoint list tags it.
    "google-vertex/europe": "Google",
    "amazon-bedrock": "Amazon Bedrock",
    "azure": "Azure",
    "claude-on-aws": "Claude Platform on AWS",
}
_CLAUDE_PROVIDER_LABELS = {
    "anthropic": "Anthropic",
    "google-vertex": "Google (Vertex AI)",
    "google-vertex/europe": "Google (Vertex AI, Europa)",
    "amazon-bedrock": "Amazon (Bedrock)",
    "azure": "Microsoft (Azure)",
    "claude-on-aws": "Claude Platform on AWS",
}
#: The models this setting pins: Anthropic's, whoever hosts them.
CLAUDE_MODELS = "anthropic/"
#: The hosts the privacy documents name for them (`matrix.LISTED_PROCESSORS`),
#: in the list's order: the only ones the pin accepts.
LISTED_HOSTS = tuple(
    dict.fromkeys(
        chain.host for chain in LISTED_PROCESSORS if chain.model.startswith(CLAUDE_MODELS)
    )
)

CLAUDE_PROVIDER = SettingSpec(
    key="model_port.privacy.claude_provider",
    type="enum",
    # The owner's choice of 04.10.2026: Google's Vertex AI in Europe — a host
    # with a zero-data-retention endpoint for these models, which Anthropic's
    # own endpoint at OpenRouter is not.
    default="google-vertex/europe",
    scopes=("platform",),
    # Every host OpenRouter has for these models, so an operator sees what
    # exists; one the documents do not name says so and is refused when chosen.
    values=tuple(
        (
            slug,
            {
                locale: _CLAUDE_PROVIDER_LABELS[slug]
                if slug in LISTED_HOSTS
                else words.format(model=_CLAUDE_PROVIDER_LABELS[slug])
                for locale, words in _UNLISTED.items()
            },
        )
        for slug in CLAUDE_PROVIDERS
    ),
    label={"pl": "Dostawca modeli Claude", "en": "Provider of the Claude models"},
    model_description="The one host that may serve a request to a Claude model "
    "(anthropic/*) through OpenRouter: Google's Vertex AI in Europe by default — the "
    "processor the platform's privacy documents name. The request names this host alone "
    "and allows no fallback, and an answer that came from another provider is an error "
    "(the answer names the provider, not its region). The other rules still hold: a "
    "request with personal data needs a zero-data-retention endpoint, so a host that has "
    "none for the model (Anthropic's own, Azure) serves nothing and the call fails "
    "(configuration / no_provider) instead of going elsewhere. Change it only together "
    "with the documents: the host named here is who processes the companies' content.",
    help={
        "pl": "Jedyny dostawca, który może wykonać zapytanie do modelu Claude. Domyślnie "
        "Google (Vertex AI, Europa) — ten, którego nazywają dokumenty prywatności "
        "platformy. Zapytanie nie trafia do nikogo innego: gdy wskazany dostawca nie może "
        "go wykonać — także dlatego, że nie ma dla tego modelu serwera bez przechowywania "
        "danych, którego wymagają zapytania z danymi osobowymi (tak jest u samego "
        "Anthropic) — zadanie kończy się błędem. Zmiana dostawcy wymaga najpierw zmiany "
        "dokumentów prywatności.",
        "en": "The only provider that may serve a request to a Claude model. Google "
        "(Vertex AI, Europe) by default — the one the platform's privacy documents name. A "
        "request goes to nobody else: when the named provider cannot serve it — also "
        "because it has no zero-data-retention endpoint for the model, which requests with "
        "personal data need (Anthropic's own has none) — the task ends with an error. "
        "Changing the provider needs the privacy documents changed first.",
    },
)


def host_not_listed(slug: str) -> tuple[str, str]:
    """The refusal of a host outside the listed chain: what has to happen first."""
    return (
        f"Dostawcy {_CLAUDE_PROVIDER_LABELS.get(slug, slug)} nie można wybrać: dokumenty "
        "prywatności platformy nazywają innego wykonawcę modeli Claude — "
        f"{', '.join(_CLAUDE_PROVIDER_LABELS[host] for host in LISTED_HOSTS)}. Najpierw zmień "
        "wpis „Podmiot przetwarzający” (docs/architecture/model-port.md) w polityce "
        "prywatności i umowie powierzenia, potem wiersz listy LISTED_PROCESSORS w kodzie "
        "portu modeli — dopiero wtedy da się go tu wybrać.",
        "processor_not_listed",
    )


def _only_listed_host(
    _before: Mapping[str, Any], after: Mapping[str, Any]
) -> Mapping[str, tuple[str, str]]:
    """The pin names a host of the listed chain — refused at the change and
    its preview, on the key the operator was changing."""
    chosen = str(after[CLAUDE_PROVIDER.field])
    return {} if chosen in LISTED_HOSTS else {CLAUDE_PROVIDER.field: host_not_listed(chosen)}


PRIVACY = SettingGroup(
    key="model_port.privacy",
    module="shared.model-port",
    title={"pl": "Prywatność zapytań do modeli AI", "en": "Privacy of requests to AI models"},
    description={
        "pl": "Którzy dostawcy modeli mogą dostać zapytania platformy.",
        "en": "Which model providers may receive the platform's requests.",
    },
    permission=SETTINGS_MANAGE,
    area=AI_AREA.key,
    platform_check=_only_listed_host,
    settings=(NO_TRAINING, CLAUDE_PROVIDER),
)

#: The platform group: the tasks' models (task key → setting key).
TASK_MODEL_SETTINGS = {TRANSLATION_TASK: TRANSLATION_MODEL.key}

TASKS = SettingGroup(
    key="model_port.tasks",
    module="shared.model-port",
    title={"pl": "Modele zadań AI", "en": "AI task models"},
    description={
        "pl": "Który model obsługuje które zadanie AI platformy.",
        "en": "Which model serves which AI task of the platform.",
    },
    # A platform group: no company writes it, so the permission is only the
    # registry's requirement that some composed module declares one.
    permission=SETTINGS_MANAGE,
    area=AI_AREA.key,
    platform_check=_only_listed,
    settings=(TRANSLATION_MODEL,),
)
