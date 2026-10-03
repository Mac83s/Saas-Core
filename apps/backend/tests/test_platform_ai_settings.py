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
