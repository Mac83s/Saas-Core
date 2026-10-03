"""An original taken down while its translations are published on their own
(TL21, translation-sources.md §8.3 pkt 3): a person decides whether they go
too. The source is the real `sites.entry` (TL11b) and its test driver.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from django.test import override_settings

from saas_core.modules.shared.sites.collections import withdraw_entry
from saas_core.modules.shared.sites.models import ContentEntryState
from saas_core.modules.shared.translation.demand import SOURCE_WITHDRAWN
from saas_core.modules.shared.translation.models import TranslationReviewItem
from saas_core.modules.shared.translation.review import ReviewChoice, decide_review
from test_sites_entry_translation_source import SitesEntryDriver, _as, _job

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("german_on_the_platform"),
]


@pytest.fixture
def german_on_the_platform() -> Any:
    with override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de")):
        yield


def withdrawn_article(driver: SitesEntryDriver, capture: Any) -> UUID:
    article = driver.create(["Alfa"])
    driver.publish(article)
    _job(driver, article)  # the German translation is public on its own
    with capture(execute=True), _as(driver.publisher):
        withdraw_entry(entry_id=article)
    return article


def open_items(driver: SitesEntryDriver) -> list[TranslationReviewItem]:
    return list(
        TranslationReviewItem.all_objects.filter(
            organization_id=driver.publisher.organization_id, state="open"
        )
    )


def test_taking_an_article_down_asks_whether_its_translation_goes_too(
    django_capture_on_commit_callbacks: Any,
) -> None:
    driver = SitesEntryDriver()
    article = withdrawn_article(driver, django_capture_on_commit_callbacks)
    (item,) = open_items(driver)
    assert (item.source_key, item.object_id, item.locale, item.reason) == (
        "sites.entry",
        article,
        "de",
        SOURCE_WITHDRAWN,
    )
    # Nothing goes down until a person decides.
    assert driver.public_texts(article, "de") == ["[de] Alfa"]
    with _as(driver.publisher):
        decide_review(
            action="accept",
            choices=[ReviewChoice(id=item.id, version=item.version)],
            idempotency_key="tl21-withdraw-accept",
        )
    assert driver.public_texts(article, "de") is None
    assert driver.sibling(article, "de").state == ContentEntryState.WITHDRAWN
    assert open_items(driver) == []


def test_discarding_keeps_the_translation_online(django_capture_on_commit_callbacks: Any) -> None:
    driver = SitesEntryDriver()
    article = withdrawn_article(driver, django_capture_on_commit_callbacks)
    (item,) = open_items(driver)
    with _as(driver.publisher):
        decide_review(
            action="discard",
            choices=[ReviewChoice(id=item.id, version=item.version)],
            idempotency_key="tl21-withdraw-discard",
        )
    assert driver.public_texts(article, "de") == ["[de] Alfa"]
    assert open_items(driver) == []
