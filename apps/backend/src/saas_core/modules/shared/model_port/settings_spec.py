"""The model a task uses, as a platform setting (TL22; answer 53 of 03.10).

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
