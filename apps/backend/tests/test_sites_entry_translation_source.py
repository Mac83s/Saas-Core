"""`sites.entry` keeps the translation source contract (ADR-069, ADR-070 pkt 16,
plan TL11b; `docs/architecture/translation-sources.md` §11), plus what only
articles do: a sibling of its own, its tags and title, and a person's
article in another language left alone."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid7

import pytest
from django.core.cache import cache
from django.db import transaction
from django.test import override_settings
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from saas_core.content_protocol.provenance import ORIGIN_COPY, ORIGIN_INTEGRATION, Provenance
from saas_core.content_protocol.sources import ReviewItem
from saas_core.content_protocol.units import unit_hash
from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.context import (
    TenantContext,
    acting_context,
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
    OrganizationStatus,
    Role,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)
from saas_core.modules.shared.sites.collections import (
    create_collection,
    create_entry,
    create_entry_translation,
    publish_entry,
    record_entry_translation,
    record_entry_version,
    save_entry_draft,
    set_entry_tags,
    update_entry_metadata,
    withdraw_entry,
)
from saas_core.modules.shared.sites.entry_translation_source import (
    ENTRY_SOURCE,
    EXCLUDED_HUMAN_VERSION,
    EXCLUDED_NOT_SOURCE,
    META_EXCERPT,
    META_TITLE,
)
from saas_core.modules.shared.sites.localized_bodies import assemble, extract_units
from saas_core.modules.shared.sites.models import (
    ContentEntry,
    ContentEntryState,
    Domain,
    DomainKind,
    DomainStatus,
    DomainTlsStatus,
)
from saas_core.modules.shared.sites.permissions import SITE_PUBLISH
from saas_core.modules.shared.sites.services import create_site
from saas_core.testing.translation_sources import (
    AUTOMATIC,
    REVIEW,
    TranslationSourceContract,
    UnitSpec,
    captured_source_changes,
    translation_policy_override,
)
from test_sites_api import csrf_value, sites_client

pytestmark = pytest.mark.django_db


@contextmanager
def _as(context: TenantContext) -> Iterator[None]:
    with transaction.atomic():
        set_local_organization_id(context.organization_id)
        with activate_tenant_context(context):
            yield


def _key() -> str:
    return str(uuid7())


class SitesEntryDriver:
    source = ENTRY_SOURCE
    capabilities = frozenset({"placeholder"})
    extra_unit_keys = frozenset({META_TITLE, META_EXCERPT})

    def __init__(self) -> None:
        user = User.objects.create_user(email=f"entry-source-{uuid7()}@example.test")
        user.status = UserStatus.ACTIVE
        user.save()
        organization = Organization.objects.create(
            name="Studio Kontrakt",
            slug=f"kontrakt-{uuid7().hex[-12:]}",
            status=OrganizationStatus.ACTIVE,
            public_locales=["pl", "de"],
        )
        EntitlementSnapshot.all_objects.create(
            organization=organization,
            subscription_state=SubscriptionState.ACTIVE,
            access_mode=AccessMode.FULL,
            features={"sites.enabled": True},
            quotas={"sites.max": 1000},
            sources={"sites.enabled": {"kind": "plan"}, "sites.max": {"kind": "plan"}},
        )
        membership = Membership.objects.create(
            organization=organization,
            user=user,
            role=Role.objects.get(key="owner", organization=None, organization_type=""),
        )
        self.publisher = context_from_membership(membership)
        self.editor = replace(
            self.publisher, permissions=self.publisher.permissions - {SITE_PUBLISH}
        )
        self.site_id: UUID | None = None
        self.collection_id: UUID | None = None
        self.count = 0

    def acting(self, context: TenantContext) -> TenantContext:
        return acting_context(context, via="ai_translation", ref=f"translation_job:{uuid7()}")

    # -- the article

    def create(self, units: Sequence[str | UnitSpec], *, legal: bool = False) -> UUID:
        with _as(self.publisher):
            if self.site_id is None:
                self.site_id = create_site(
                    name="Kontrakt",
                    slug=f"k-{uuid7().hex[-12:]}",
                    default_locale="pl",
                    idempotency_key=_key(),
                ).value.id
                self.collection_id = create_collection(
                    site_id=self.site_id,
                    key="blog",
                    name="Blog",
                    kind="blog",
                    base_path="blog",
                    idempotency_key=_key(),
                )[0].id
            assert self.collection_id is not None
            self.count += 1
            entry, _created = create_entry(
                collection_id=self.collection_id,
                slug=f"wpis-{self.count}",
                locale="pl",
                title="Wpis testowy",
                idempotency_key=_key(),
            )
            update_entry_metadata(entry_id=entry.id, excerpt="Zajawka wpisu", author_name="Anna")
            self._save(entry.id, [self._block(unit) for unit in units])
        Domain.all_objects.filter(site_id=self.site_id, kind=DomainKind.PLATFORM).update(
            status=DomainStatus.VERIFIED, tls_status=DomainTlsStatus.ELIGIBLE
        )
        return entry.id

    @staticmethod
    def _block(unit: str | UnitSpec) -> dict[str, Any]:
        text = unit if isinstance(unit, str) else unit.text
        return {"block_type": "core.rich_text", "schema_version": 1, "data": {"text": text}}

    @staticmethod
    def _blocks(entry_id: UUID) -> list[dict[str, Any]]:
        entry = ContentEntry.all_objects.select_related("current_draft").get(pk=entry_id)
        return [
            {
                "block_type": block["block_type"],
                "schema_version": block["schema_version"],
                "data": dict(block["data"]),
            }
            for block in entry.current_draft.blocks
        ]

    @staticmethod
    def _save(entry_id: UUID, blocks: list[dict[str, Any]]) -> None:
        entry = ContentEntry.all_objects.get(pk=entry_id)
        save_entry_draft(
            entry_id=entry_id,
            expected_version=entry.version,
            blocks=blocks,
            media_asset_ids=[],
            idempotency_key=_key(),
        )

    def _change(self, entry_id: UUID, change: Any) -> None:
        with _as(self.publisher):
            blocks = self._blocks(entry_id)
            change(blocks)
            self._save(entry_id, blocks)

    def insert(self, object_id: UUID, index: int, text: str) -> None:
        self._change(object_id, lambda blocks: blocks.insert(index, self._block(text)))

    def move(self, object_id: UUID, from_index: int, to_index: int) -> None:
        self._change(object_id, lambda blocks: blocks.insert(to_index, blocks.pop(from_index)))

    def edit(self, object_id: UUID, index: int, text: str) -> None:
        def change(blocks: list[dict[str, Any]]) -> None:
            blocks[index] = self._block(text)

        self._change(object_id, change)

    def delete(self, object_id: UUID, index: int) -> None:
        self._change(object_id, lambda blocks: blocks.pop(index))

    def publish(self, object_id: UUID) -> None:
        with _as(self.publisher):
            publish_entry(entry_id=object_id, idempotency_key=_key())

    # -- the article in the language

    @staticmethod
    def sibling(object_id: UUID, locale: str) -> ContentEntry | None:
        entry = ContentEntry.all_objects.get(pk=object_id)
        return (
            ContentEntry.all_objects.select_related("current_draft__source_version")
            .filter(translation_group=entry.translation_group, locale=locale)
            .first()
        )

    def write_as_person(self, object_id: UUID, locale: str, index: int, text: str) -> None:
        with _as(self.publisher):
            sibling = self.sibling(object_id, locale)
            assert sibling is not None
            blocks = self._blocks(sibling.id)
            blocks[index]["data"]["text"] = text
            self._save(sibling.id, blocks)
            # The person publishes their correction, as they would in the panel.
            publish_entry(entry_id=sibling.id, idempotency_key=_key())

    def write_as_integration(self, object_id: UUID, locale: str, index: int, text: str) -> None:
        with _as(self.publisher):
            sibling = self.sibling(object_id, locale)
            assert sibling is not None and sibling.current_draft is not None
            draft = sibling.current_draft
            unit = extract_units(draft.source_version.blocks)[index]
            units = dict(draft.units)
            units[unit.key] = {
                "text": text,
                "provenance": _provenance(ORIGIN_INTEGRATION, unit, text),
            }
            self._store(sibling, draft.source_version, units, "integration")
            publish_entry(entry_id=sibling.id, idempotency_key=_key())

    def copy_source(self, object_id: UUID, locale: str) -> None:
        """A machine sibling holding the source's own words, not yet public."""
        with _as(self.publisher):
            entry = ContentEntry.all_objects.select_related("current_publication").get(pk=object_id)
            version = entry.versions.get(number=entry.current_publication.snapshot["version"])
            sibling = record_entry_translation(
                self.publisher,
                entry,
                locale=locale,
                slug=f"kopie-{self.count}",
                title=entry.title,
                idempotency_key=_key(),
                request_hash="0" * 64,
                machine=True,
            )
            units = {
                unit.key: {
                    "text": unit.text,
                    "provenance": _provenance(ORIGIN_COPY, unit, unit.text),
                }
                for unit in extract_units(version.blocks)
            }
            self._store(sibling, version, units, "copy")

    def _store(
        self, sibling: ContentEntry, source: Any, units: dict[str, Any], origin: str
    ) -> None:
        texts = {
            key: str(entry["text"]) for key, entry in units.items() if not key.startswith("meta/")
        }
        record_entry_version(
            self.publisher,
            sibling,
            blocks=assemble(source.blocks, texts).blocks,
            media_asset_ids=[],
            idempotency_key=_key(),
            request_hash="0" * 64,
            units=units,
            source_version=source,
            origin=origin,
        )

    def public_texts(self, object_id: UUID, locale: str) -> list[str] | None:
        sibling = self.sibling(object_id, locale)
        if sibling is None or sibling.current_publication is None:
            return None
        host = Domain.all_objects.get(site_id=self.site_id, kind=DomainKind.PLATFORM).hostname
        cache.clear()
        with override_settings(PUBLIC_SITE_SCHEME="https"):
            response = APIClient().get(
                "/api/v1/public/site/",
                {"path": sibling.current_publication.snapshot["path"]},
                HTTP_HOST=host,
            )
        if response.status_code != 200 or response.data["locale"] != locale:
            return None
        return [str(block["data"]["text"]) for block in response.data["blocks"]]


def _provenance(origin: str, unit: Any, text: str) -> dict[str, Any]:
    return Provenance(
        origin=origin,
        source_hash=unit.source_hash,
        written_hash=unit_hash(unit.kind, text),
        model="",
        at=datetime.now(UTC).isoformat(),
    ).as_dict()


@pytest.fixture(autouse=True)
def german_on_the_platform() -> Iterator[None]:
    with override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de")):
        yield


class TestSitesEntrySource(TranslationSourceContract):
    source_key = "sites.entry"

    @pytest.fixture
    def driver(self) -> SitesEntryDriver:
        return SitesEntryDriver()


# -- what only articles do ----------------------------------------------------


def _job(driver: SitesEntryDriver, object_id: UUID, *, policy: Any = AUTOMATIC) -> Any:
    with translation_policy_override(policy):
        return TestSitesEntrySource().translate(driver, object_id)


def test_a_job_makes_the_article_in_the_language_with_its_title_tags_and_date():
    driver = SitesEntryDriver()
    article = driver.create(["Jak dbać o kopyta"])
    with _as(driver.publisher):
        set_entry_tags(entry_id=article, names=["Porady"])
    driver.publish(article)

    with captured_source_changes() as notices:
        result = _job(driver, article)

    assert result.decisions == [("live", None)]
    assert notices == []
    source = ContentEntry.all_objects.get(pk=article)
    sibling = driver.sibling(article, "de")
    assert sibling.translation_of_id == article
    assert (sibling.title, sibling.excerpt) == ("[de] Wpis testowy", "[de] Zajawka wpisu")
    assert sibling.slug == "de-wpis-testowy"
    assert sibling.author_name == "Anna"
    assert [link.tag.slug for link in sibling.tag_links.all()] == ["porady"]
    assert sibling.state == ContentEntryState.PUBLISHED
    assert sibling.published_at == source.published_at
    assert sibling.current_publication.snapshot["origin"] == {"origin": "ai", "reviewed": False}
    assert driver.public_texts(article, "de") == ["[de] Jak dbać o kopyta"]


def test_a_machine_translation_is_never_a_source():
    driver = SitesEntryDriver()
    article = driver.create(["Alfa"])
    driver.publish(article)
    _job(driver, article)
    sibling = driver.sibling(article, "de")

    listed = ENTRY_SOURCE.list_objects(context=driver.publisher, cursor=None, limit=10)
    read = ENTRY_SOURCE.read(
        context=driver.acting(driver.publisher),
        object_id=sibling.id,
        locale="pl",
        basis="published",
    )

    assert [item.object_id for item in listed.items] == [article]
    assert listed.items[0].public
    assert read.excluded == EXCLUDED_NOT_SOURCE
    with captured_source_changes() as notices, _as(driver.publisher):
        publish_entry(entry_id=sibling.id, idempotency_key=_key())
    assert notices == []


def test_a_persons_own_article_in_the_language_is_left_alone():
    driver = SitesEntryDriver()
    article = driver.create(["Alfa"])
    driver.publish(article)
    with _as(driver.publisher):
        theirs, _created = create_entry_translation(
            entry_id=article, locale="de", slug="eigener", title="Eigener", idempotency_key=_key()
        )
    # Still empty: the first translation takes it on; the title they typed
    # is theirs and is not sent.
    taken = _job(driver, article)
    assert taken.decisions == [("live", None)]
    adopted = ContentEntry.all_objects.get(pk=theirs.id)
    assert (adopted.translation_of_id, adopted.title, adopted.slug) == (
        article,
        "Eigener",
        "eigener",
    )
    assert adopted.excerpt == "[de] Zajawka wpisu"
    assert driver.public_texts(article, "de") == ["[de] Alfa"]

    other = driver.create(["Beta"])
    driver.publish(other)
    with _as(driver.publisher):
        written, _created = create_entry_translation(
            entry_id=other, locale="de", slug="selbst", title="Selbst", idempotency_key=_key()
        )
        save_entry_draft(
            entry_id=written.id,
            expected_version=0,
            blocks=[driver._block("Selbst geschrieben"), driver._block("Noch ein Absatz")],
            media_asset_ids=[],
            idempotency_key=_key(),
        )
    read = ENTRY_SOURCE.read(
        context=driver.acting(driver.publisher), object_id=other, locale="de", basis="published"
    )
    assert read.excluded == EXCLUDED_HUMAN_VERSION


def test_a_person_accepts_a_waiting_translation_and_it_goes_out():
    driver = SitesEntryDriver()
    article = driver.create(["Alfa"])
    driver.publish(article)
    waiting = _job(driver, article, policy=REVIEW)
    assert waiting.decisions == [("pending", "review_mode")]
    assert driver.public_texts(article, "de") is None

    accepted = ENTRY_SOURCE.review(
        context=driver.publisher,
        action="accept",
        items=[ReviewItem(object_id=article, locale="de", expected_version=None)],
        idempotency_key=f"review:{_key()}",
    )

    assert [(o.state, o.reason) for o in accepted] == [("live", None)]
    assert driver.public_texts(article, "de") == ["[de] Alfa"]
    assert driver.sibling(article, "de").title == "[de] Wpis testowy"


def test_discarding_a_waiting_translation_keeps_nothing_of_it():
    driver = SitesEntryDriver()
    article = driver.create(["Alfa"])
    driver.publish(article)
    _job(driver, article, policy=REVIEW)

    discarded = ENTRY_SOURCE.review(
        context=driver.publisher,
        action="discard",
        items=[ReviewItem(object_id=article, locale="de", expected_version=None)],
        idempotency_key=f"review:{_key()}",
    )

    assert [(o.state, o.reason) for o in discarded] == [("refused", "discarded")]
    sibling = driver.sibling(article, "de")
    assert (sibling.pending_version_id, sibling.current_draft_id) == (None, None)


def test_reverting_the_first_job_takes_the_translation_down_again():
    driver = SitesEntryDriver()
    article = driver.create(["Alfa"])
    driver.publish(article)
    _job(driver, article)
    job_ref = driver.sibling(article, "de").current_draft.origin_ref

    outcomes = ENTRY_SOURCE.revert(
        context=driver.acting(driver.publisher), job_ref=job_ref, idempotency_key=_key()
    )

    assert [(o.object_id, o.state, o.reason) for o in outcomes] == [(article, "live", "reverted")]
    sibling = driver.sibling(article, "de")
    assert (sibling.state, sibling.current_draft_id) == (ContentEntryState.DRAFT, None)
    assert driver.public_texts(article, "de") is None


def test_reverting_a_later_job_puts_back_what_visitors_read_before_it():
    driver = SitesEntryDriver()
    article = driver.create(["Alfa"])
    driver.publish(article)
    _job(driver, article)
    driver.edit(article, 0, "Alfa nowa")
    driver.publish(article)
    _job(driver, article)
    assert driver.public_texts(article, "de") == ["[de] Alfa nowa"]
    job_ref = driver.sibling(article, "de").current_draft.origin_ref

    ENTRY_SOURCE.revert(
        context=driver.acting(driver.publisher), job_ref=job_ref, idempotency_key=_key()
    )

    assert driver.public_texts(article, "de") == ["[de] Alfa"]
    sibling = driver.sibling(article, "de")
    assert sibling.current_publication.snapshot["path"] == "/de/blog/de-wpis-testowy/"


def test_withdrawing_the_source_asks_about_its_translations():
    driver = SitesEntryDriver()
    article = driver.create(["Alfa"])
    driver.publish(article)

    with captured_source_changes() as notices, _as(driver.publisher):
        withdraw_entry(entry_id=article)

    assert [(n.source_key, n.object_ids, n.change) for n in notices] == [
        ("sites.entry", (article,), "withdrawn")
    ]


def test_republishing_the_same_text_is_no_change():
    driver = SitesEntryDriver()
    article = driver.create(["Alfa"])
    driver.publish(article)

    with captured_source_changes() as notices:
        driver.publish(article)

    assert notices == []


def test_a_persons_title_on_a_translation_is_theirs():
    driver = SitesEntryDriver()
    article = driver.create(["Alfa"])
    driver.publish(article)
    _job(driver, article)
    sibling = driver.sibling(article, "de")
    with _as(driver.publisher):
        update_entry_metadata(entry_id=sibling.id, title="Mein Titel")
        update_entry_metadata(entry_id=article, title="Wpis zmieniony")
    driver.publish(article)

    # The source's new title is not sent over the person's.
    assert _job(driver, article).decisions == []
    full = ENTRY_SOURCE.read(
        context=driver.acting(driver.publisher), object_id=article, locale="de", basis="published"
    )
    assert full.targets[META_TITLE].text == "Mein Titel"
    assert full.targets[META_TITLE].provenance is None
    assert driver.sibling(article, "de").title == "Mein Titel"


def test_entry_metadata_changes_only_what_is_sent():
    driver = SitesEntryDriver()
    article = driver.create(["Alfa"])
    with _as(driver.publisher):
        entry = update_entry_metadata(entry_id=article, noindex=True)
        assert (entry.title, entry.excerpt, entry.author_name, entry.noindex) == (
            "Wpis testowy",
            "Zajawka wpisu",
            "Anna",
            True,
        )
        with pytest.raises(ValidationError):
            update_entry_metadata(entry_id=article, title="   ")
    events = OrganizationAuditEntry.objects.filter(
        target_id=article, action="sites.entry.metadata_updated"
    ).order_by("id")
    assert [event.metadata["fields"] for event in events] == [
        ["author_name", "excerpt"],
        ["noindex"],
    ]


def test_the_metadata_endpoint_answers_with_the_entry():
    client, organization, user = sites_client(
        slug=f"entry-meta-{uuid7().hex[-8:]}", role_key="owner"
    )
    context = context_from_membership(Membership.objects.get(organization=organization, user=user))
    with _as(context):
        site = create_site(
            name="Meta", slug=f"m-{uuid7().hex[-12:]}", default_locale="pl", idempotency_key=_key()
        ).value
        collection, _created = create_collection(
            site_id=site.id,
            key="blog",
            name="Blog",
            kind="blog",
            base_path="blog",
            idempotency_key=_key(),
        )
        entry, _created = create_entry(
            collection_id=collection.id,
            slug="wpis",
            locale="pl",
            title="Wpis",
            idempotency_key=_key(),
        )

    response = client.patch(
        f"/api/v1/sites/entries/{entry.id}/metadata/",
        {"title": "Nowy tytuł", "author_name": ""},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )

    assert response.status_code == 200, response.data
    assert (response.data["title"], response.data["author_name"]) == ("Nowy tytuł", "")
    assert response.data["translation_of"] is None
    assert response.data["pending_reason"] == ""


def test_accepting_a_proposal_keeps_what_the_same_job_published():
    driver = SitesEntryDriver()
    article = driver.create(["Alfa", "Beta"])
    driver.publish(article)
    _job(driver, article)
    driver.write_as_person(article, "de", 1, "Beta poprawiona")
    driver.edit(article, 0, "Alfa nowa")
    driver.edit(article, 1, "Beta nowa")
    driver.publish(article)
    result = _job(driver, article)
    assert result.decisions == [("live", None), ("pending", "overwrites_human")]
    assert driver.public_texts(article, "de") == ["[de] Alfa nowa", "Beta poprawiona"]

    ENTRY_SOURCE.review(
        context=driver.publisher,
        action="accept",
        items=[ReviewItem(object_id=article, locale="de", expected_version=None)],
        idempotency_key=f"review:{_key()}",
    )

    assert driver.public_texts(article, "de") == ["[de] Alfa nowa", "[de] Beta nowa"]


def test_the_assistant_decides_with_the_reviews_consent_on_pages_and_articles():
    """One label for a person's decision on a waiting translation, whichever
    source holds it, so the consent the review asks for is enough."""
    from saas_core.modules.core.organizations.person_gate import PersonRequired
    from saas_core.modules.shared.sites.language_decisions import REVIEW_GATE
    from saas_core.modules.shared.sites.translation_source import PAGE_SOURCE
    from test_sites_page_translation_source import SitesPageDriver, TestSitesPageSource

    pages = SitesPageDriver()
    home = pages.create(["Witamy"])
    pages.publish(home)
    with translation_policy_override(REVIEW):
        TestSitesPageSource().translate(pages, home)
    articles = SitesEntryDriver()
    article = articles.create(["Alfa"])
    articles.publish(article)
    _job(articles, article, policy=REVIEW)

    for source, driver, object_id in (
        (PAGE_SOURCE, pages, home),
        (ENTRY_SOURCE, articles, article),
    ):
        assistant = acting_context(driver.publisher, via="assistant", ref=f"conversation:{uuid7()}")
        item = ReviewItem(object_id=object_id, locale="de", expected_version=None)
        with pytest.raises(PersonRequired):
            source.review(
                context=replace(assistant, acting_opened=frozenset({"Usunięcie języka firmy"})),
                action="accept",
                items=[item],
                idempotency_key=_key(),
            )
        accepted = source.review(
            context=replace(assistant, acting_opened=frozenset({REVIEW_GATE})),
            action="accept",
            items=[item],
            idempotency_key=_key(),
        )
        assert [(o.state, o.reason) for o in accepted] == [("live", None)]


def test_a_person_takes_the_translations_down_after_the_original():
    driver = SitesEntryDriver()
    article = driver.create(["Alfa"])
    driver.publish(article)
    _job(driver, article)
    with _as(driver.publisher):
        withdraw_entry(entry_id=article)
    assert driver.public_texts(article, "de") == ["[de] Alfa"]

    taken = ENTRY_SOURCE.review(
        context=driver.publisher,
        action="withdraw",
        items=[ReviewItem(object_id=article, locale="de", expected_version=None)],
        idempotency_key=_key(),
    )

    assert [(o.state, o.reason) for o in taken] == [("draft", "withdrawn")]
    assert driver.public_texts(article, "de") is None
    assert driver.sibling(article, "de").state == ContentEntryState.WITHDRAWN
