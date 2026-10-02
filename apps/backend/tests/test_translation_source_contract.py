"""The translation source contract (docs/architecture/translation-sources.md §11).

Both in-memory sources pass the suite every module's adapter must pass, and
every source a module registers has its own subclass of the contract.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from django.apps import apps

from saas_core.content_protocol.registry import TESTING_PREFIX, translation_sources
from saas_core.testing.translation_sources import (
    FakeDraftSource,
    FakeLiveRecordSource,
    FakeSourceDriver,
    TranslationSourceContract,
    registered_translation_source,
)

TESTS = Path(__file__).parent


class TestFakeDraftSource(TranslationSourceContract):
    source_key = "testing.draft"

    @pytest.fixture
    def driver(self) -> Iterator[FakeSourceDriver]:
        with registered_translation_source(FakeDraftSource(self.source_key)) as source:
            yield FakeSourceDriver(source)


class TestFakeLiveRecordSource(TranslationSourceContract):
    source_key = "testing.live_record"

    @pytest.fixture
    def driver(self) -> Iterator[FakeSourceDriver]:
        with registered_translation_source(FakeLiveRecordSource(self.source_key)) as source:
            yield FakeSourceDriver(source)


def test_every_registered_source_has_a_contract_test() -> None:
    """A new source without its contract test stops CI, in products too."""
    contracts = [
        path.read_text(encoding="utf-8")
        for path in TESTS.rglob("test_*.py")
        if "TranslationSourceContract" in path.read_text(encoding="utf-8")
    ]
    for source in translation_sources():
        if source.key.startswith(TESTING_PREFIX):
            continue
        config = apps.get_containing_app_config(type(source).__module__)
        assert config is not None, source.key
        assert source.key.split(".")[0] == config.label, source.key
        assert any(f'source_key = "{source.key}"' in text for text in contracts), source.key
