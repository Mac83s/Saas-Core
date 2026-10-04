"""The model a task uses, and which hosts may serve it, as platform settings
(TL22; answer 53 of 03.10; „karty osób” 04.10).

Class A: only the platform sets it — `platform_setting set
model_port.tasks.translation_text <model> --operator … --reason …` today, the
„Platforma” panel later. The choice is one of the matrix rows a live probe
confirmed that have every capability the task needs; a value that stops
being one (a row removed in a later commit) is ignored and the task's own
default applies.
"""

from __future__ import annotations

from saas_core.modules.core.organizations.api import (
    SettingArea,
    SettingGroup,
    SettingSpec,
)
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE

from .matrix import MODELS
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


def selectable_models(task: str) -> tuple[str, ...]:
    """Probed rows with every capability the task needs, not evals-only."""
    spec = next(spec for spec in DEFAULT_TASKS if spec.key == task)
    return tuple(
        profile.model
        for (adapter, _model), profile in MODELS.items()
        if adapter == spec.adapter
        and profile.probed is not None
        and not profile.evaluation_only
        and spec.capabilities <= profile.capabilities
    )


_TRANSLATION_DEFAULT = next(spec for spec in DEFAULT_TASKS if spec.key == TRANSLATION_TASK)

TRANSLATION_MODEL = SettingSpec(
    key="model_port.tasks.translation_text",
    type="enum",
    default=_TRANSLATION_DEFAULT.model,
    scopes=("platform",),
    values=tuple(
        (model, {"pl": model, "en": model}) for model in selectable_models(TRANSLATION_TASK)
    ),
    label={"pl": "Model tłumaczeń", "en": "Translation model"},
    model_description="The model the translation.text task calls through OpenRouter: one of "
    "the probed rows of the model matrix that support JSON schema output. Changing it "
    "changes cost and quality for every company; evals in docs/evals/translation compare "
    "the candidates. The platform's privacy documents name OpenRouter with Claude Sonnet "
    "5.5 (Anthropic) as the processor of companies' content: another model needs those "
    "documents changed first.",
    help={
        "pl": "Model, który tłumaczy treści wszystkich firm. Koszt i jakość kandydatów: "
        "evale w docs/evals/translation. Dokumenty prywatności platformy wymieniają "
        "OpenRouter z modelem Claude Sonnet 5.5 (Anthropic) — inny model wymaga najpierw "
        "zmiany tych dokumentów.",
        "en": "The model that translates every company's content. Candidates' cost and "
        "quality: the evals in docs/evals/translation. The platform's privacy documents "
        "name OpenRouter with Claude Sonnet 5.5 (Anthropic) — another model needs those "
        "documents changed first.",
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

CLAUDE_PROVIDER = SettingSpec(
    key="model_port.privacy.claude_provider",
    type="enum",
    default="anthropic",
    scopes=("platform",),
    values=tuple(
        (slug, {"pl": _CLAUDE_PROVIDER_LABELS[slug], "en": _CLAUDE_PROVIDER_LABELS[slug]})
        for slug in CLAUDE_PROVIDERS
    ),
    label={"pl": "Dostawca modeli Claude", "en": "Provider of the Claude models"},
    model_description="The one host that may serve a request to a Claude model "
    "(anthropic/*) through OpenRouter: Anthropic itself by default — the processor the "
    "platform's privacy documents name. The request names this host alone and allows no "
    "fallback, and an answer that came from another host is an error. The other rules "
    "still hold: a request with personal data needs a zero-data-retention endpoint, so a "
    "host that has none for the model serves nothing and the call fails "
    "(configuration / no_provider) instead of going elsewhere. Change it only together "
    "with the documents: the host named here is who processes the companies' content.",
    help={
        "pl": "Jedyny dostawca, który może wykonać zapytanie do modelu Claude. Domyślnie "
        "Anthropic — ten, którego nazywają dokumenty prywatności platformy. Zapytanie "
        "nie trafia do nikogo innego: gdy wskazany dostawca nie może go wykonać — także "
        "dlatego, że nie ma dla tego modelu serwera bez przechowywania danych, którego "
        "wymagają zapytania z danymi osobowymi — zadanie kończy się błędem. Zmiana "
        "dostawcy wymaga najpierw zmiany dokumentów prywatności.",
        "en": "The only provider that may serve a request to a Claude model. Anthropic by "
        "default — the one the platform's privacy documents name. A request goes to nobody "
        "else: when the named provider cannot serve it — also because it has no "
        "zero-data-retention endpoint for the model, which requests with personal data "
        "need — the task ends with an error. Changing the provider needs the privacy "
        "documents changed first.",
    },
)


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
    settings=(TRANSLATION_MODEL,),
)
