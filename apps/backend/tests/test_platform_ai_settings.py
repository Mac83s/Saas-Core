"""The translation model and price as platform settings (TL22; answers 53
and 54a of 03.10): an operator's choice above the environment and the code,
only among probed models, and a price billing charges through its owner."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache

from saas_core.modules.core.organizations import platform_settings
from saas_core.modules.core.organizations.settings_registry import setting_group
from saas_core.modules.shared.billing.api import operation_cost
from saas_core.modules.shared.model_port.registry import task_spec
from saas_core.modules.shared.model_port.settings_spec import (
    TRANSLATION_MODEL,
    selectable_models,
)
from saas_core.modules.shared.translation.settings_spec import PRICE

pytestmark = pytest.mark.django_db

SONNET = "anthropic/claude-sonnet-5.5"
HAIKU = "anthropic/claude-haiku-4.5"


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


def test_the_model_is_chosen_among_probed_rows_and_never_an_evals_only_one() -> None:
    offered = [value for value, _labels in TRANSLATION_MODEL.values]
    assert offered == list(selectable_models("translation.text"))
    assert SONNET in offered and HAIKU in offered
    assert not any(model.startswith("deepseek/") for model in offered)
    assert TRANSLATION_MODEL.default == SONNET


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


def test_a_model_that_stopped_being_selectable_is_ignored(chosen: dict[str, Any]) -> None:
    chosen[TRANSLATION_MODEL.key] = "deepseek/deepseek-v4-pro"

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
