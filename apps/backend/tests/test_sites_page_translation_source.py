"""`sites.page` keeps the translation source contract (ADR-069, plan TL11a;
`docs/architecture/translation-sources.md` §11), plus what only pages do."""

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
from rest_framework.test import APIClient

from saas_core.content_protocol.provenance import ORIGIN_INTEGRATION, Provenance
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
    OrganizationStatus,
    Role,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)
from saas_core.modules.shared.sites.language_decisions import publish_locale_version
from saas_core.modules.shared.sites.language_versions import (
    _create_version,
    copy_source_into_locale_body,
    get_locale_body,
    save_locale_body,
)
from saas_core.modules.shared.sites.models import (
    Domain,
    DomainKind,
    DomainStatus,
    DomainTlsStatus,
    Page,
    PageBlock,
    PageTranslation,
    PageType,
    Site,
)
from saas_core.modules.shared.sites.permissions import SITE_PUBLISH
from saas_core.modules.shared.sites.services import (
    create_page,
    create_site,
    publish_site,
    save_draft,
    save_page_translation,
    set_page_type,
)
from saas_core.modules.shared.sites.translation_source import (
    META_DESCRIPTION,
    META_TITLE,
    PAGE_SOURCE,
)
from saas_core.testing.translation_sources import TranslationSourceContract, UnitSpec

pytestmark = pytest.mark.django_db


@contextmanager
def _as(context: TenantContext) -> Iterator[None]:
    with transaction.atomic():
        set_local_organization_id(context.organization_id)
        with activate_tenant_context(context):
            yield


def _key() -> str:
    return str(uuid7())


class SitesPageDriver:
    source = PAGE_SOURCE
    capabilities = frozenset({"legal", "placeholder"})
    extra_unit_keys = frozenset({META_TITLE, META_DESCRIPTION})

    def __init__(self) -> None:
        user = User.objects.create_user(email=f"page-source-{uuid7()}@example.test")
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
        self.sites: dict[UUID, UUID] = {}
        self.site_id: UUID | None = None

    def acting(self, context: TenantContext) -> TenantContext:
        return acting_context(context, via="ai_translation", ref=f"translation_job:{uuid7()}")

    # -- the page's source

    def create(self, units: Sequence[str | UnitSpec], *, legal: bool = False) -> UUID:
        """A page of the driver's one site: the first is its home page, so a
        language comes onto the site with the first object translated."""
        with _as(self.publisher):
            if self.site_id is None:
                self.site_id = create_site(
                    name="Kontrakt",
                    slug=f"k-{uuid7().hex[-12:]}",
                    default_locale="pl",
                    idempotency_key=_key(),
                ).value.id
            number = len(self.sites) + 1
            page = create_page(
                site_id=self.site_id,
                name=f"Strona {number}",
                key=f"strona-{number}",
                idempotency_key=_key(),
            ).value
            self._save(page.id, [self._block(unit) for unit in units])
            save_page_translation(
                page_id=page.id,
                locale="pl",
                expected_version=0,
                slug=f"strona-{number}",
                title="Strona testowa",
                description="Opis strony",
                social_title="",
                social_description="",
                allow_title_fallback=False,
                allow_description_fallback=False,
                allow_social_title_fallback=False,
                allow_social_description_fallback=False,
                idempotency_key=_key(),
            )
            if legal:
                set_page_type(page_id=page.id, page_type=PageType.LEGAL)
        Domain.all_objects.filter(site_id=self.site_id, kind=DomainKind.PLATFORM).update(
            status=DomainStatus.VERIFIED, tls_status=DomainTlsStatus.ELIGIBLE
        )
        self.sites[page.id] = self.site_id
        return page.id

    @staticmethod
    def _block(unit: str | UnitSpec) -> dict[str, Any]:
        text = unit if isinstance(unit, str) else unit.text
        return {"block_type": "core.rich_text", "schema_version": 1, "data": {"text": text}}

    def _blocks(self, page_id: UUID) -> list[dict[str, Any]]:
        page = Page.all_objects.get(pk=page_id)
        return [
            {
                "block_type": block.block_type,
                "schema_version": block.schema_version,
                "data": dict(block.data),
            }
            for block in PageBlock.all_objects.filter(
                page_version_id=page.current_draft_id
            ).order_by("position")
        ]

    def _save(self, page_id: UUID, blocks: list[dict[str, Any]]) -> None:
        page = Page.all_objects.select_related("current_draft").get(pk=page_id)
        version = page.current_draft.number if page.current_draft else 0
        save_draft(
            page_id=page_id,
            expected_version=version,
            blocks=blocks,
            media_asset_ids=[],
            idempotency_key=_key(),
        )

    def _change(self, page_id: UUID, change: Any) -> None:
        with _as(self.publisher):
            blocks = self._blocks(page_id)
            change(blocks)
            self._save(page_id, blocks)

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
            publish_site(site_id=self.sites[object_id], idempotency_key=_key())

    # -- the language's text

    def _unit_key(self, object_id: UUID, locale: str, index: int) -> tuple[Any, str]:
        body = get_locale_body(page_id=object_id, locale=locale)
        return body, body.units[index].unit.key

    def write_as_person(self, object_id: UUID, locale: str, index: int, text: str) -> None:
        with _as(self.publisher):
            body, key = self._unit_key(object_id, locale, index)
            save_locale_body(
                page_id=object_id,
                locale=locale,
                source_version_id=body.source_version.id,
                expected_body_version=body.translation.body_version,
                units={key: text},
                idempotency_key=_key(),
            )
            # A correction of a public version goes out by the person's own
            # "Publish this language version" (ADR-070 pkt 12).
            publish_locale_version(page_id=object_id, locale=locale, idempotency_key=_key())

    def write_as_integration(self, object_id: UUID, locale: str, index: int, text: str) -> None:
        with _as(self.publisher):
            body, key = self._unit_key(object_id, locale, index)
            unit = body.units[index].unit
            units = dict(body.version.units)
            units[key] = {
                "text": text,
                "provenance": Provenance(
                    origin=ORIGIN_INTEGRATION,
                    source_hash=unit.source_hash,
                    written_hash=unit_hash(unit.kind, text),
                    model="",
                    at=datetime.now(UTC).isoformat(),
                ).as_dict(),
            }
            row = body.translation
            version = _create_version(
                page=body.page,
                translation=row,
                source_version=body.source_version,
                units=units,
                actor_id=self.publisher.actor_id,
                credential_id=None,
                origin="integration",
                origin_ref="",
                idempotency_key=_key(),
                request_hash="0" * 64,
            )
            PageTranslation.all_objects.filter(pk=row.pk).update(
                body_current=version, body_version=row.body_version + 1
            )
            publish_locale_version(page_id=object_id, locale=locale, idempotency_key=_key())

    def copy_source(self, object_id: UUID, locale: str) -> None:
        with _as(self.publisher):
            if not PageTranslation.all_objects.filter(page_id=object_id, locale=locale).exists():
                save_page_translation(
                    page_id=object_id,
                    locale=locale,
                    expected_version=0,
                    slug="kopie",
                    title="Kopie",
                    description="Kopie der Seite",
                    social_title="",
                    social_description="",
                    allow_title_fallback=False,
                    allow_description_fallback=False,
                    allow_social_title_fallback=False,
                    allow_social_description_fallback=False,
                    idempotency_key=_key(),
                )
            body = get_locale_body(page_id=object_id, locale=locale)
            copy_source_into_locale_body(
                page_id=object_id,
                locale=locale,
                source_version_id=body.source_version.id,
                expected_body_version=body.translation.body_version,
                idempotency_key=_key(),
            )

    def public_texts(self, object_id: UUID, locale: str) -> list[str] | None:
        host = Domain.all_objects.get(
            site_id=self.sites[object_id], kind=DomainKind.PLATFORM
        ).hostname
        row = PageTranslation.all_objects.filter(page_id=object_id, locale=locale).first()
        home = next(iter(self.sites)) == object_id
        path = f"/{locale}/" if home else f"/{locale}/{row.slug if row else 'brak'}/"
        cache.clear()
        with override_settings(PUBLIC_SITE_SCHEME="https"):
            response = APIClient().get("/api/v1/public/site/", {"path": path}, HTTP_HOST=host)
        if response.status_code != 200 or response.data["locale"] != locale:
            return None
        return [str(block["data"]["text"]) for block in response.data["blocks"]]


@pytest.fixture(autouse=True)
def german_on_the_platform() -> Iterator[None]:
    with override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de")):
        yield


class TestSitesPageSource(TranslationSourceContract):
    source_key = "sites.page"

    @pytest.fixture
    def driver(self) -> SitesPageDriver:
        return SitesPageDriver()


# -- what only pages do -------------------------------------------------------


def _job(contract: TestSitesPageSource, driver: SitesPageDriver, object_id: UUID) -> Any:
    from saas_core.testing.translation_sources import AUTOMATIC, translation_policy_override

    with translation_policy_override(AUTOMATIC):
        return contract.translate(driver, object_id)


def test_a_job_writes_the_title_and_publishes_only_what_it_translated():
    from saas_core.modules.shared.sites.models import Publication

    contract, driver = TestSitesPageSource(), SitesPageDriver()
    home = driver.create(["Witamy w studiu"])
    driver.publish(home)
    # Unpublished Polish work elsewhere on the page stays a draft.
    driver.edit(home, 0, "Szkic, którego nie widać")
    result = _job(contract, driver, home)

    assert result.decisions == [("live", None)]
    row = PageTranslation.all_objects.get(page_id=home, locale="de")
    assert (row.title, row.description) == ("[de] Strona testowa", "[de] Opis strony")
    assert row.slug == "de-strona-testowa"
    assert row.slug_locked_at is not None
    site = Site.all_objects.get(pk=driver.site_id)
    assert site.current_publication.reason == "translation_job"
    assert Publication.all_objects.filter(site=site).count() == 2
    assert driver.public_texts(home, "de") == ["[de] Witamy w studiu"]
    polish = _public(driver, home, "/")
    assert polish == ["Witamy w studiu"]


def _public(driver: SitesPageDriver, object_id: UUID, path: str) -> list[str]:
    host = Domain.all_objects.get(site_id=driver.site_id, kind=DomainKind.PLATFORM).hostname
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        response = APIClient().get("/api/v1/public/site/", {"path": path}, HTTP_HOST=host)
    return [str(block["data"]["text"]) for block in response.data["blocks"]]


def test_reverting_a_job_puts_back_what_was_public_before_it():
    contract, driver = TestSitesPageSource(), SitesPageDriver()
    home = driver.create(["Witamy"])
    driver.publish(home)
    _job(contract, driver, home)
    job_ref = PageTranslation.all_objects.get(page_id=home, locale="de").body_current.origin_ref

    outcomes = PAGE_SOURCE.revert(
        context=driver.acting(driver.publisher), job_ref=job_ref, idempotency_key=f"revert:{_key()}"
    )

    assert [(o.state, o.reason) for o in outcomes] == [("live", "reverted")]
    site = Site.all_objects.get(pk=driver.site_id)
    assert site.current_publication.reason == "translation_revert"
    assert driver.public_texts(home, "de") is None


def test_a_person_accepts_a_waiting_translation_with_its_title():
    from saas_core.testing.translation_sources import REVIEW, translation_policy_override

    contract, driver = TestSitesPageSource(), SitesPageDriver()
    home = driver.create(["Witamy"])
    driver.publish(home)
    with translation_policy_override(REVIEW):
        waiting = contract.translate(driver, home)
    assert waiting.decisions == [("pending", "review_mode")]
    assert driver.public_texts(home, "de") is None

    accepted = PAGE_SOURCE.review(
        context=driver.publisher,
        action="accept",
        items=[ReviewItem(object_id=home, locale="de", expected_version=None)],
        idempotency_key=f"review:{_key()}",
    )

    assert [(o.state, o.reason) for o in accepted] == [("live", None)]
    assert driver.public_texts(home, "de") == ["[de] Witamy"]
    row = PageTranslation.all_objects.get(page_id=home, locale="de")
    assert row.title == "[de] Strona testowa"


def test_pages_are_listed_home_first_with_their_public_state():
    driver = SitesPageDriver()
    home = driver.create(["Witamy"])
    other = driver.create(["Oferta"])
    driver.publish(home)

    page = PAGE_SOURCE.list_objects(context=driver.publisher, cursor=None, limit=10)

    assert [(item.object_id, item.priority) for item in page.items] == [(home, 0), (other, 1)]
    assert all(item.scope == str(driver.site_id) for item in page.items)
    assert all(item.public for item in page.items)


def test_reverting_a_job_never_brings_back_a_discarded_translation():
    from saas_core.modules.shared.sites.language_decisions import reject_locale_version
    from saas_core.testing.translation_sources import (
        REVIEW,
        fixed_translation,
        translation_policy_override,
    )

    contract, driver = TestSitesPageSource(), SitesPageDriver()
    home = driver.create(["Witamy"])
    driver.publish(home)
    with translation_policy_override(REVIEW):
        contract.translate(driver, home, text=fixed_translation("Willkommen"))
    row = PageTranslation.all_objects.get(page_id=home, locale="de")
    with _as(driver.publisher):
        reject_locale_version(
            page_id=home,
            locale="de",
            expected_body_version=row.body_version,
            idempotency_key=_key(),
        )
    _job(contract, driver, home)
    job_ref = PageTranslation.all_objects.get(page_id=home, locale="de").body_current.origin_ref

    PAGE_SOURCE.revert(
        context=driver.acting(driver.publisher), job_ref=job_ref, idempotency_key=f"revert:{_key()}"
    )

    assert PageTranslation.all_objects.get(page_id=home, locale="de").body_current is None
    assert driver.public_texts(home, "de") is None


def test_accepting_a_proposal_keeps_what_the_same_job_published():
    contract, driver = TestSitesPageSource(), SitesPageDriver()
    home = driver.create(["Alfa", "Beta"])
    driver.publish(home)
    _job(contract, driver, home)
    driver.write_as_person(home, "de", 1, "Beta poprawiona")
    driver.edit(home, 0, "Alfa nowa")
    driver.edit(home, 1, "Beta nowa")
    driver.publish(home)
    result = _job(contract, driver, home)
    assert result.decisions == [("live", None), ("pending", "overwrites_human")]

    PAGE_SOURCE.review(
        context=driver.publisher,
        action="accept",
        items=[ReviewItem(object_id=home, locale="de", expected_version=None)],
        idempotency_key=f"review:{_key()}",
    )

    assert driver.public_texts(home, "de") == ["[de] Alfa nowa", "[de] Beta nowa"]
