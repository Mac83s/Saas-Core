"""The translation model and price as platform settings (TL22; answers 53
and 54a of 03.10): an operator's choice above the environment and the code,
only among probed models, and a price billing charges through its owner."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.organizations import platform_settings
from saas_core.modules.core.organizations.platform_settings import checked_platform_value
from saas_core.modules.core.organizations.settings_registry import setting_group
from saas_core.modules.shared.billing.api import operation_cost
from saas_core.modules.shared.model_port.matrix import LISTED_PROCESSORS
from saas_core.modules.shared.model_port.registry import task_spec
from saas_core.modules.shared.model_port.settings_spec import (
    CLAUDE_PROVIDER,
    LISTED_HOSTS,
    NO_TRAINING,
    TRANSLATION_MODEL,
    capable_models,
    selectable_models,
)
from saas_core.modules.shared.translation.settings_spec import PRICE

pytestmark = pytest.mark.django_db

SONNET = "anthropic/claude-sonnet-5.5"
HAIKU = "anthropic/claude-haiku-4.5"
GEMINI = "google/gemini-3.8-flash"


@pytest.fixture
def chosen(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The operators' values, as the platform settings table would give them."""
    values: dict[str, Any] = {}
    cache.clear()
    monkeypatch.setattr(platform_settings, "platform_overrides", lambda: values)
    return values


def test_both_are_platform_only_keys_in_the_ai_area() -> None:
    for spec in (TRANSLATION_MODEL, PRICE):
        assert spec.scopes == ("platform",)
        assert spec.operator_level == 2
        assert setting_group(spec.group).area == "ai"


def test_the_model_is_chosen_among_the_processors_the_documents_name() -> None:
    """The task sends companies' content: an operator may choose only a model
    the privacy documents cover. The panel still shows every probed row the
    task could use, and says in its name which ones the documents leave out."""
    assert selectable_models("translation.text") == (SONNET, HAIKU)
    assert {(chain.adapter, chain.model) for chain in LISTED_PROCESSORS} == {
        ("openrouter", SONNET),
        ("openrouter", HAIKU),
    }
    labels = {value: names for value, names in TRANSLATION_MODEL.values}
    assert list(labels) == list(capable_models("translation.text"))
    assert labels[SONNET] == {"pl": SONNET, "en": SONNET}
    assert labels[GEMINI]["pl"] == f"{GEMINI} — poza listą podmiotów przetwarzających"
    assert "not on the list of processors" in labels["deepseek/deepseek-v4-pro"]["en"]
    assert TRANSLATION_MODEL.default == SONNET


@pytest.mark.parametrize("model", [GEMINI, "deepseek/deepseek-v4-pro", "anthropic/claude-opus-5.5"])
def test_a_model_outside_the_listed_processors_is_refused_with_what_comes_first(
    model: str,
) -> None:
    with pytest.raises(ValidationError) as refused:
        checked_platform_value(TRANSLATION_MODEL.key, model)

    (message,) = refused.value.detail["value"]
    assert message.code == "processor_not_listed"
    assert str(message) == (
        f"Modelu {model} nie można wybrać: dokumenty prywatności platformy nie wymieniają "
        "podmiotu, który przetwarzałby wtedy treść firm. Najpierw dopisz go do polityki "
        "prywatności i umowy powierzenia (wpis „Podmiot przetwarzający” w "
        "docs/architecture/model-port.md), potem do listy LISTED_PROCESSORS w kodzie portu "
        "modeli — dopiero wtedy da się go tu wybrać. Dziś na liście: Claude Sonnet 5.5 i "
        "Claude Haiku 4.5 (Anthropic), uruchamiane w Google Cloud (Vertex AI, region "
        "europejski), przez OpenRouter."
    )


def test_the_provider_pin_takes_only_the_host_the_documents_name() -> None:
    """`model_port.privacy.claude_provider` names who runs the Claude models:
    the listed chain's host, and no other until the documents name it."""
    assert CLAUDE_PROVIDER.default == "google-vertex/europe"
    assert LISTED_HOSTS == ("google-vertex/europe",)
    assert {chain.host for chain in LISTED_PROCESSORS} == set(LISTED_HOSTS)
    labels = {value: names for value, names in CLAUDE_PROVIDER.values}
    assert labels["google-vertex/europe"]["pl"] == "Google (Vertex AI, Europa)"
    assert labels["anthropic"]["pl"] == "Anthropic — poza listą podmiotów przetwarzających"
    assert labels["amazon-bedrock"]["en"] == "Amazon (Bedrock) — not on the list of processors"

    assert checked_platform_value(CLAUDE_PROVIDER.key, "google-vertex/europe") == (
        "google-vertex/europe"
    )
    assert checked_platform_value(CLAUDE_PROVIDER.key, None) is None
    for host in ("anthropic", "amazon-bedrock", "google-vertex", "azure"):
        with pytest.raises(ValidationError) as refused:
            checked_platform_value(CLAUDE_PROVIDER.key, host)
        (message,) = refused.value.detail["value"]
        assert message.code == "processor_not_listed"
        assert "nie można wybrać: dokumenty prywatności platformy nazywają innego wykonawcę" in (
            str(message)
        )
        assert "Google (Vertex AI, Europa). Najpierw zmień wpis „Podmiot przetwarzający”" in (
            str(message)
        )
    # The other key of the group is not held back by the pin's rule.
    assert checked_platform_value(NO_TRAINING.key, False) is False


def test_the_translation_model_can_still_be_changed_within_the_listed_set() -> None:
    assert checked_platform_value(TRANSLATION_MODEL.key, HAIKU) == HAIKU
    assert checked_platform_value(TRANSLATION_MODEL.key, SONNET) == SONNET
    # Giving the key back is never refused.
    assert checked_platform_value(TRANSLATION_MODEL.key, None) is None
    with pytest.raises(ValidationError) as unknown:
        checked_platform_value(TRANSLATION_MODEL.key, "nobody/no-model")
    assert unknown.value.detail["value"][0].code == "invalid_choice"


def test_an_operators_model_comes_before_the_environment_and_the_code(
    chosen: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = task_spec("translation.text")
    assert spec is not None and spec.model == SONNET

    monkeypatch.setenv("MODEL_PORT_TASK_TRANSLATION_TEXT_MODEL", "google/gemini-3.8-flash")
    by_env = task_spec("translation.text")
    assert by_env is not None and by_env.model == "google/gemini-3.8-flash"

    chosen[TRANSLATION_MODEL.key] = HAIKU
    by_operator = task_spec("translation.text")
    assert by_operator is not None and by_operator.model == HAIKU
    # The startup checks read no settings.
    unread = task_spec("translation.text", platform=False)
    assert unread is not None and unread.model == "google/gemini-3.8-flash"


@pytest.mark.parametrize("stale", ["deepseek/deepseek-v4-pro", GEMINI, "gone/removed-row"])
def test_a_stored_model_that_is_not_selectable_is_ignored(
    chosen: dict[str, Any], stale: str
) -> None:
    """A row removed since, an evals-only one, or a model an operator chose
    before the listed set existed: the task keeps its own model."""
    chosen[TRANSLATION_MODEL.key] = stale

    spec = task_spec("translation.text")

    assert spec is not None and spec.model == SONNET


def test_the_price_is_the_platform_setting(chosen: dict[str, Any]) -> None:
    assert operation_cost("translation.characters", 3) == 3

    chosen[PRICE.key] = 2

    assert operation_cost("translation.characters", 3) == 6


# --- The engine's keys (TL22) --------------------------------------------------------


def test_the_engines_keys_are_the_platforms_and_tuning_needs_no_step_up() -> None:
    from saas_core.modules.shared.translation import settings_spec as engine

    group = setting_group("translation.engine")
    assert group.area == "ai"
    levels = {spec.field: spec.operator_level for spec in group.settings}
    assert levels == {
        "demand_wait_minutes": 1,
        "demand_max_wait_minutes": 1,
        "mass_publication_cap": 1,
        "leftover_threshold_percent": 1,
        "length_ratio_max_percent": 1,
        # Money of the deployment: level 2.
        "platform_confirm_usd": 2,
    }
    assert all(spec.scopes == ("platform",) for spec in group.settings)
    assert engine.ENGINE is group


def test_without_an_operator_the_engine_runs_on_the_values_it_always_had(
    chosen: dict[str, Any],
) -> None:
    from datetime import timedelta

    from saas_core.modules.shared.translation import settings_spec as engine
    from saas_core.modules.shared.translation.quality import DEFAULT_THRESHOLDS

    assert engine.demand_wait() == timedelta(minutes=5)
    assert engine.demand_max_wait() == timedelta(minutes=30)
    assert engine.mass_publication_cap() == 20
    assert engine.platform_confirm_usd_micros() == 5_000_000
    # The code's thresholds and the keys' defaults are one pair of numbers.
    assert engine.quality_thresholds() == DEFAULT_THRESHOLDS


def test_an_operators_value_is_read_at_use_time(chosen: dict[str, Any]) -> None:
    from datetime import timedelta

    from saas_core.modules.shared.translation import settings_spec as engine
    from saas_core.modules.shared.translation.engine_policy import ENGINE_POLICY
    from test_booking import membership

    owner = membership("tl22-engine")
    chosen.update({
        "translation.engine.demand_wait_minutes": 2,
        "translation.engine.mass_publication_cap": 3,
        "translation.engine.leftover_threshold_percent": 50,
        "translation.engine.length_ratio_max_percent": 400,
        "translation.engine.platform_confirm_usd": 0,
    })

    assert engine.demand_wait() == timedelta(minutes=2)
    assert ENGINE_POLICY.policy(organization_id=owner.organization_id).mass_publication_cap == 3
    thresholds = engine.quality_thresholds()
    assert (thresholds.leftover_share, thresholds.length_ratio) == (0.5, 4.0)
    assert engine.platform_confirm_usd_micros() == 0


def test_the_deployments_value_sits_between_the_operator_and_the_code(
    chosen: dict[str, Any], settings: Any
) -> None:
    from saas_core.modules.shared.translation import settings_spec as engine

    settings.TRANSLATION_MASS_PUBLICATION_CAP = 7
    current = platform_settings.read_platform_setting(engine.MASS_PUBLICATION_CAP.key)
    assert (current.value, current.source) == (7, "deployment")

    chosen[engine.MASS_PUBLICATION_CAP.key] = 4
    current = platform_settings.read_platform_setting(engine.MASS_PUBLICATION_CAP.key)
    assert (current.value, current.source) == (4, "platform")


def test_the_quality_thresholds_decide_what_is_flagged() -> None:
    from saas_core.content_protocol.units import Unit
    from saas_core.modules.shared.translation.quality import (
        QA_SOURCE_LEFTOVERS,
        QualityThresholds,
        check_soft,
    )
    from saas_core.modules.shared.translation.segments import plan_calls

    source = "zapraszamy serdecznie wszystkich klientów naszego studia projektowego codziennie rano"
    half = "wir laden herzlich alle klientów naszego studia projektowego codziennie rano"
    unit = Unit(key="0/text", kind="text", text=source, data_class="public", max_length=None)
    segment = plan_calls([[unit]])[0].segments[0]

    assert QA_SOURCE_LEFTOVERS in check_soft(segment, half, glossary=(), target_script="Latn")
    lenient = QualityThresholds(leftover_share=0.95)
    assert QA_SOURCE_LEFTOVERS not in check_soft(
        segment, half, glossary=(), target_script="Latn", thresholds=lenient
    )


# --- The platform's default for two company keys (TL22) -----------------------------


def _state(owner: Any) -> dict[str, Any]:
    from saas_core.modules.shared.translation.services import settings_state
    from test_booking import tenant

    with tenant(owner):
        values: dict[str, Any] = settings_state(owner.organization_id)["values"]
    return values


def test_the_operators_default_reaches_a_company_that_chose_nothing(
    chosen: dict[str, Any], settings: Any
) -> None:
    from saas_core.modules.shared.translation.engine_policy import company_mode
    from saas_core.modules.shared.translation.settings_spec import AUTO_MONTHLY_LIMIT, MODE
    from test_booking import membership

    settings.SETTINGS_DEFAULTS = {}
    settings.MODEL_PORT_PROCESSOR_LISTED = True
    owner = membership("tl22-default")
    assert MODE.scopes == AUTO_MONTHLY_LIMIT.scopes == ("platform", "organization")
    assert company_mode(owner.organization_id) == ("automatic", "code")

    chosen.update({MODE.key: "review", AUTO_MONTHLY_LIMIT.key: 40})

    assert company_mode(owner.organization_id) == ("review", "platform")
    values = _state(owner)
    mode = values[MODE.key]
    assert (mode["effective"], mode["source"]) == ("review", "platform")
    # A default, not a lock: the company may still choose its own.
    assert (mode["locked"], mode["lock_reason"]) == (False, None)
    limit = values[AUTO_MONTHLY_LIMIT.key]
    assert (limit["effective"], limit["source"], limit["locked"]) == (40, "platform", False)


def test_a_products_default_stands_above_the_operators(
    chosen: dict[str, Any], settings: Any
) -> None:
    """ADR-078 pkt 3: a platform-wide change must not move a product off what
    it chose — MedPlano starts with review whatever the platform says."""
    from saas_core.modules.shared.translation.engine_policy import company_mode
    from saas_core.modules.shared.translation.settings_spec import AUTO_MONTHLY_LIMIT, MODE
    from test_booking import membership

    settings.SETTINGS_DEFAULTS = {MODE.key: "review", AUTO_MONTHLY_LIMIT.key: 30}
    settings.MODEL_PORT_PROCESSOR_LISTED = True
    owner = membership("tl22-product")
    chosen.update({MODE.key: "automatic", AUTO_MONTHLY_LIMIT.key: 500})

    assert company_mode(owner.organization_id) == ("review", "product")
    values = _state(owner)
    assert values[MODE.key]["source"] == "product"
    limit = values[AUTO_MONTHLY_LIMIT.key]
    assert (limit["effective"], limit["source"]) == (30, "product")


def test_a_companys_own_choice_stands_above_both(chosen: dict[str, Any], settings: Any) -> None:
    from saas_core.modules.shared.translation.engine_policy import company_mode
    from saas_core.modules.shared.translation.models import TranslationSettings
    from saas_core.modules.shared.translation.settings_spec import AUTO_MONTHLY_LIMIT, MODE
    from test_booking import membership, tenant

    settings.SETTINGS_DEFAULTS = {}
    settings.MODEL_PORT_PROCESSOR_LISTED = True
    owner = membership("tl22-own")
    with tenant(owner):
        TranslationSettings.all_objects.create(
            organization=owner.organization, mode="automatic", auto_monthly_limit=10
        )
    chosen.update({MODE.key: "review", AUTO_MONTHLY_LIMIT.key: 40})

    assert company_mode(owner.organization_id) == ("automatic", "organization")
    limit = _state(owner)[AUTO_MONTHLY_LIMIT.key]
    assert (limit["effective"], limit["source"]) == (10, "organization")


def test_the_deployments_switch_still_locks_whatever_the_default_says(
    chosen: dict[str, Any], settings: Any
) -> None:
    from saas_core.modules.shared.translation.models import TranslationCeiling
    from saas_core.modules.shared.translation.settings_spec import MODE
    from test_booking import membership
    from test_sites_ai_badge import operator

    settings.SETTINGS_DEFAULTS = {}
    settings.MODEL_PORT_PROCESSOR_LISTED = True
    owner = membership("tl22-ceiling")
    chosen[MODE.key] = "automatic"
    TranslationCeiling.objects.create(state="review", reason="przegląd", changed_by=operator())

    mode = _state(owner)[MODE.key]

    assert (mode["effective"], mode["locked"]) == ("review", True)
    assert mode["lock_reason"] is not None


def test_the_longest_wait_is_never_set_below_the_wait() -> None:
    """Refused at the change, on whichever key the operator moves — not
    corrected when the engine reads it."""
    from rest_framework.exceptions import ValidationError

    from saas_core.modules.core.organizations.platform_settings import (
        change_platform_setting,
        checked_platform_value,
    )
    from saas_core.modules.shared.translation import settings_spec as engine
    from test_sites_ai_badge import operator

    cache.clear()
    staff = operator()
    wait, longest = engine.DEMAND_WAIT_MINUTES.key, engine.DEMAND_MAX_WAIT_MINUTES.key

    # The wait raised above the longest wait (30).
    with pytest.raises(ValidationError) as raised:
        change_platform_setting(wait, 40, operator=staff, reason="Próba")
    assert raised.value.get_codes() == {"value": ["above_longest_wait"]}
    # The longest wait cannot go below the wait (5): its own lower bound is 5.
    assert checked_platform_value(longest, 5) == 5
    assert checked_platform_value(wait, 30) == 30
