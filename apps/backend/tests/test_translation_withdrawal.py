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


def test_removing_an_article_asks_the_same_and_its_translation_can_follow(
    django_capture_on_commit_callbacks: Any,
) -> None:
    """A removed article has left its translation group; what a job
    translated from it still names it, which is how the person's answer
    reaches the translation (ADR-079, „Uzupełnienie CT2")."""
    from saas_core.modules.shared.sites.entry_removal import remove_entry
    from saas_core.modules.shared.sites.models import ContentEntry

    driver = SitesEntryDriver()
    article = driver.create(["Alfa"])
    driver.publish(article)
    _job(driver, article)
    with django_capture_on_commit_callbacks(execute=True), _as(driver.publisher):
        remove_entry(entry_id=article)

    (item,) = open_items(driver)
    assert (item.object_id, item.locale, item.reason) == (article, "de", SOURCE_WITHDRAWN)
    german = ContentEntry.all_objects.get(translation_of_id=article)
    assert german.state == ContentEntryState.PUBLISHED
    with _as(driver.publisher):
        decide_review(
            action="accept",
            choices=[ReviewChoice(id=item.id, version=item.version)],
            idempotency_key="ct2-removed-accept",
        )
    german.refresh_from_db()
    assert german.state == ContentEntryState.WITHDRAWN
    assert open_items(driver) == []


def test_a_question_about_an_erased_article_closes_instead_of_failing(
    django_capture_on_commit_callbacks: Any,
) -> None:
    """The article and its translation were removed and erased with their
    type while the queue still asked about them. The person's decision gets
    an answer and the item closes — it cannot wait for good on rows that are
    gone."""
    from saas_core.modules.shared.sites.content_types import delete_content_type
    from saas_core.modules.shared.sites.entry_removal import remove_entry
    from saas_core.modules.shared.sites.models import ContentCollection, ContentEntry

    driver = SitesEntryDriver()
    article = driver.create(["Alfa"])
    driver.publish(article)
    _job(driver, article)
    german = ContentEntry.all_objects.get(translation_of_id=article)
    assert driver.collection_id is not None
    with django_capture_on_commit_callbacks(execute=True), _as(driver.publisher):
        remove_entry(entry_id=article)
    (item,) = open_items(driver)
    assert item.reason == SOURCE_WITHDRAWN
    with django_capture_on_commit_callbacks(execute=True), _as(driver.publisher):
        remove_entry(entry_id=german.id)
        name = ContentCollection.all_objects.get(pk=driver.collection_id).name
        delete_content_type(collection_id=driver.collection_id, confirm_name=name)
    assert not ContentEntry.with_removed.filter(pk__in=[article, german.id]).exists()
    assert [found.id for found in open_items(driver)] == [item.id]

    with _as(driver.publisher):
        decide_review(
            action="accept",
            choices=[ReviewChoice(id=item.id, version=item.version)],
            idempotency_key="ct2-erased-accept",
        )
    assert open_items(driver) == []
