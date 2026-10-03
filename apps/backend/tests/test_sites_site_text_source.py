"""`sites.site_texts` keeps the translation source contract (ADR-069, ADR-070
pkt 15, plan TL11c; `docs/architecture/translation-sources.md` §11), plus what
only site texts do: a footer reordered keeps its translations, a reworded
tagline shows the new source text marked with its language until translated."""

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
    OrganizationStatus,
    Role,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)
from saas_core.modules.shared.sites.appearance import (
    default_appearance,
    get_site_appearance,
    save_site_appearance,
)
from saas_core.modules.shared.sites.collections import create_collection
from saas_core.modules.shared.sites.models import (
    Domain,
    DomainKind,
    DomainStatus,
    DomainTlsStatus,
    Site,
    SiteTextTranslation,
)
from saas_core.modules.shared.sites.permissions import SITE_PUBLISH
from saas_core.modules.shared.sites.services import (
    create_page,
    create_site,
    publish_site,
    save_draft,
    save_page_translation,
)
from saas_core.modules.shared.sites.site_text_source import SITE_TEXT_SOURCE
from saas_core.modules.shared.sites.site_texts import (
    KEY_TAGLINE,
    list_site_texts,
    localize_appearance,
    publish_site_texts,
    save_site_texts,
    site_text_units,
    store_row,
)
from saas_core.testing.translation_sources import (
    AUTOMATIC,
    REVIEW,
    TranslationSourceContract,
    UnitSpec,
    captured_source_changes,
    translation_policy_override,
)

pytestmark = pytest.mark.django_db


@contextmanager
def _as(context: TenantContext) -> Iterator[None]:
    with transaction.atomic():
        set_local_organization_id(context.organization_id)
        with activate_tenant_context(context):
            yield


def _key() -> str:
    return str(uuid7())


class SiteTextsDriver:
    """Each object is a site of its own; its units are its footer's link
    labels, each link at an address of its own."""

    source = SITE_TEXT_SOURCE
    capabilities: frozenset[str] = frozenset()

    def __init__(self) -> None:
        user = User.objects.create_user(email=f"site-texts-{uuid7()}@example.test")
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
        self.links = 0

    def acting(self, context: TenantContext) -> TenantContext:
        return acting_context(context, via="ai_translation", ref=f"translation_job:{uuid7()}")

    # -- the site's texts

    def create(self, units: Sequence[str | UnitSpec], *, legal: bool = False) -> UUID:
        """A site already public with its home page, whose footer is about to
        go out with the next publication."""
        with _as(self.publisher):
            site = create_site(
                name="Kontrakt",
                slug=f"k-{uuid7().hex[-12:]}",
                default_locale="pl",
                idempotency_key=_key(),
            ).value
            home_page(site.id)
            publish_site(site_id=site.id, idempotency_key=_key())
            self._save(site.id, [self._link(unit) for unit in units])
        Domain.all_objects.filter(site_id=site.id, kind=DomainKind.PLATFORM).update(
            status=DomainStatus.VERIFIED, tls_status=DomainTlsStatus.ELIGIBLE
        )
        return site.id

    def _link(self, unit: str | UnitSpec) -> dict[str, str]:
        self.links += 1
        return {"label": unit if isinstance(unit, str) else unit.text, "href": f"/s-{self.links}/"}

    @staticmethod
    def _footer(site_id: UUID) -> list[dict[str, str]]:
        return [
            dict(link)
            for link in get_site_appearance(site_id=site_id)["appearance"]["footer"]["links"]
        ]

    @staticmethod
    def _save(site_id: UUID, links: list[dict[str, str]]) -> None:
        current = get_site_appearance(site_id=site_id)
        appearance = current["appearance"]
        appearance["footer"] = {"layout": "simple", "text": "", "links": links}
        save_site_appearance(
            site_id=site_id,
            expected_version=current["version"],
            appearance=appearance,
            idempotency_key=_key(),
        )

    def _change(self, site_id: UUID, change: Any) -> None:
        with _as(self.publisher):
            links = self._footer(site_id)
            change(links)
            self._save(site_id, links)

    def insert(self, object_id: UUID, index: int, text: str) -> None:
        self._change(object_id, lambda links: links.insert(index, self._link(text)))

    def move(self, object_id: UUID, from_index: int, to_index: int) -> None:
        self._change(object_id, lambda links: links.insert(to_index, links.pop(from_index)))

    def edit(self, object_id: UUID, index: int, text: str) -> None:
        def change(links: list[dict[str, str]]) -> None:
            links[index]["label"] = text

        self._change(object_id, change)

    def delete(self, object_id: UUID, index: int) -> None:
        self._change(object_id, lambda links: links.pop(index))

    def publish(self, object_id: UUID) -> None:
        with _as(self.publisher):
            publish_site(site_id=object_id, idempotency_key=_key())

    # -- the language's texts

    def write_as_person(self, object_id: UUID, locale: str, index: int, text: str) -> None:
        with _as(self.publisher):
            texts = list_site_texts(site_id=object_id, locale=locale)
            save_site_texts(
                site_id=object_id,
                locale=locale,
                expected_version=texts.version,
                texts={texts.items[index].key: text},
            )
            publish_site_texts(site_id=object_id, locale=locale, idempotency_key=_key())

    def write_as_integration(self, object_id: UUID, locale: str, index: int, text: str) -> None:
        self._store(object_id, locale, {index: (text, ORIGIN_INTEGRATION)})
        with _as(self.publisher):
            publish_site_texts(site_id=object_id, locale=locale, idempotency_key=_key())

    def copy_source(self, object_id: UUID, locale: str) -> None:
        site = Site.all_objects.select_related("current_publication").get(pk=object_id)
        count = len(site_text_units(site, site.current_publication.snapshot.get("appearance")))
        self._store(object_id, locale, dict.fromkeys(range(count), (None, ORIGIN_COPY)))

    def _store(
        self, object_id: UUID, locale: str, writes: dict[int, tuple[str | None, str]]
    ) -> None:
        with _as(self.publisher):
            site = Site.all_objects.select_related("current_publication").get(pk=object_id)
            units = site_text_units(site, site.current_publication.snapshot.get("appearance"))
            for index, (text, origin) in writes.items():
                unit = units[index]
                value = unit.text if text is None else text
                row = store_row(site, locale, unit)
                row.text = value
                row.provenance = Provenance(
                    origin=origin,
                    source_hash=unit.source_hash,
                    written_hash=unit_hash(unit.kind, value),
                    model="",
                    at=datetime.now(UTC).isoformat(),
                ).as_dict()
                row.origin_ref = ""
                row.save()

    def public_texts(self, object_id: UUID, locale: str) -> list[str] | None:
        """The footer as a page in the language shows it; None while none of
        its texts is in that language."""
        site = Site.all_objects.select_related("current_publication").get(pk=object_id)
        snapshot = site.current_publication.snapshot
        appearance, untranslated = localize_appearance(
            snapshot.get("appearance"),
            (snapshot.get("site_texts") or {}).get(locale) or {},
            site.default_locale,
        )
        links = appearance["footer"]["links"]
        if len(untranslated) == len(links):
            return None
        return [str(link["label"]) for link in links]


def home_page(site_id: UUID) -> None:
    page = create_page(site_id=site_id, name="Start", key="start", idempotency_key=_key()).value
    save_draft(
        page_id=page.id,
        expected_version=0,
        blocks=[{"block_type": "core.rich_text", "schema_version": 1, "data": {"text": "Witamy"}}],
        media_asset_ids=[],
        idempotency_key=_key(),
    )
    save_page_translation(
        page_id=page.id,
        locale="pl",
        expected_version=0,
        slug="start",
        title="Start",
        description="Strona główna",
        social_title="",
        social_description="",
        allow_title_fallback=False,
        allow_description_fallback=False,
        allow_social_title_fallback=False,
        allow_social_description_fallback=False,
        idempotency_key=_key(),
    )


@pytest.fixture(autouse=True)
def german_on_the_platform() -> Iterator[None]:
    with override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de")):
        yield


class TestSiteTextsSource(TranslationSourceContract):
    source_key = "sites.site_texts"

    @pytest.fixture
    def driver(self) -> SiteTextsDriver:
        return SiteTextsDriver()


# -- what only site texts do --------------------------------------------------


def _job(driver: SiteTextsDriver, object_id: UUID, *, policy: Any = AUTOMATIC) -> Any:
    with translation_policy_override(policy):
        return TestSiteTextsSource().translate(driver, object_id)


def _tagline(driver: SiteTextsDriver, site_id: UUID, tagline: str) -> None:
    with _as(driver.publisher):
        current = get_site_appearance(site_id=site_id)
        appearance = current["appearance"]
        appearance["header"] = {"layout": "classic", "brand": "Kontrakt", "tagline": tagline}
        save_site_appearance(
            site_id=site_id,
            expected_version=current["version"],
            appearance=appearance,
            idempotency_key=_key(),
        )
        publish_site(site_id=site_id, idempotency_key=_key())


def test_a_reordered_footer_keeps_each_translation_with_its_link():
    driver = SiteTextsDriver()
    site = driver.create(["O nas", "Cennik", "Kontakt"])
    driver.publish(site)
    _job(driver, site)

    driver.move(site, 2, 0)
    driver.publish(site)

    assert driver.public_texts(site, "de") == ["[de] Kontakt", "[de] O nas", "[de] Cennik"]
    read = SITE_TEXT_SOURCE.read(
        context=driver.publisher, object_id=site, locale="de", basis="published"
    )
    assert TestSiteTextsSource().selection(read).units == ()


def test_a_reworded_tagline_shows_the_new_source_text_marked_until_translated():
    driver = SiteTextsDriver()
    site = driver.create(["Kontakt"])
    _tagline(driver, site, "Fryzjer w centrum")
    _job(driver, site)
    snapshot = Site.all_objects.get(pk=site).current_publication.snapshot
    assert snapshot["site_texts"]["de"][KEY_TAGLINE] == "[de] Fryzjer w centrum"

    _tagline(driver, site, "Fryzjer i kosmetyczka w centrum")

    snapshot = Site.all_objects.get(pk=site).current_publication.snapshot
    appearance, untranslated = localize_appearance(
        snapshot["appearance"], snapshot["site_texts"]["de"], "pl"
    )
    assert appearance["header"]["tagline"] == "Fryzjer i kosmetyczka w centrum"
    assert untranslated == {"header.tagline": "pl"}
    assert appearance["footer"]["links"][0]["label"] == "[de] Kontakt"


def test_a_page_in_the_language_shows_its_footer_and_marks_the_rest():
    from test_sites_page_translation_source import SitesPageDriver, TestSitesPageSource

    pages = SitesPageDriver()
    home = pages.create(["Witamy"])
    pages.publish(home)
    with translation_policy_override(AUTOMATIC):
        TestSitesPageSource().translate(pages, home)
    site = pages.site_id
    assert site is not None
    with _as(pages.publisher):
        current = get_site_appearance(site_id=site)
        appearance = current["appearance"]
        appearance["header"] = {"layout": "classic", "brand": "Kontrakt", "tagline": "Witamy"}
        appearance["footer"] = {
            "layout": "simple",
            "text": "",
            "links": [{"label": "Kontakt", "href": "/kontakt/"}],
        }
        save_site_appearance(
            site_id=site,
            expected_version=current["version"],
            appearance=appearance,
            idempotency_key=_key(),
        )
        publish_site(site_id=site, idempotency_key=_key())
        texts = list_site_texts(site_id=site, locale="de")
        link = next(item.key for item in texts.items if item.role == "footer_link")
        save_site_texts(
            site_id=site, locale="de", expected_version=texts.version, texts={link: "Kontakt"}
        )
        publish_site_texts(site_id=site, locale="de", idempotency_key=_key())
    host = Domain.all_objects.get(site_id=site, kind=DomainKind.PLATFORM).hostname
    cache.clear()

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        response = APIClient().get("/api/v1/public/site/", {"path": "/de/"}, HTTP_HOST=host)

    assert response.status_code == 200
    assert response.data["locale"] == "de"
    assert response.data["appearance"]["footer"]["links"][0]["label"] == "Kontakt"
    assert response.data["appearance_lang"] == {"header.tagline": "pl"}
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        polish = APIClient().get("/api/v1/public/site/", {"path": "/"}, HTTP_HOST=host)
    assert polish.data["appearance_lang"] == {}


def test_collection_and_tag_names_are_site_texts():
    driver = SiteTextsDriver()
    site = driver.create(["Kontakt"])
    with _as(driver.publisher):
        create_collection(
            site_id=site,
            key="blog",
            name="Porady",
            kind="blog",
            base_path="blog",
            idempotency_key=_key(),
        )
    driver.publish(site)

    texts = Site.all_objects.get(pk=site)
    roles = [
        unit.key.split("/", 1)[0]
        for unit in site_text_units(texts, texts.current_publication.snapshot["appearance"])
    ]

    assert roles == ["footer", "collection"]


def test_a_person_accepts_waiting_texts_and_they_go_out():
    driver = SiteTextsDriver()
    site = driver.create(["Kontakt"])
    driver.publish(site)
    waiting = _job(driver, site, policy=REVIEW)
    assert waiting.decisions == [("pending", "review_mode")]
    assert driver.public_texts(site, "de") is None

    accepted = SITE_TEXT_SOURCE.review(
        context=driver.publisher,
        action="accept",
        items=[ReviewItem(object_id=site, locale="de", expected_version=None)],
        idempotency_key=_key(),
    )

    assert [(o.state, o.reason) for o in accepted] == [("live", None)]
    assert driver.public_texts(site, "de") == ["[de] Kontakt"]
    assert Site.all_objects.get(pk=site).current_publication.reason == "locale_accept"


def test_reverting_a_job_puts_back_each_text_it_replaced():
    driver = SiteTextsDriver()
    site = driver.create(["Kontakt"])
    driver.publish(site)
    driver.write_as_person(site, "de", 0, "Kontakt (Hand)")
    driver.edit(site, 0, "Kontakt i dojazd")
    driver.publish(site)
    with translation_policy_override(AUTOMATIC):
        TestSiteTextsSource().translate(driver, site, protected="overwrite")
    assert driver.public_texts(site, "de") == ["[de] Kontakt i dojazd"]
    job_ref = SiteTextTranslation.all_objects.exclude(origin_ref="").get(site_id=site).origin_ref

    outcomes = SITE_TEXT_SOURCE.revert(
        context=driver.acting(driver.publisher), job_ref=job_ref, idempotency_key=_key()
    )

    assert [(o.state, o.reason) for o in outcomes] == [("live", "reverted")]
    # The job's text is gone; the person's translation of the old wording is
    # what visitors read again.
    assert driver.public_texts(site, "de") == ["Kontakt (Hand)"]


def test_a_person_saves_and_publishes_through_the_api():
    from test_sites_api import csrf_value, sites_client

    client, organization, user = sites_client(slug=f"texts-{uuid7().hex[-8:]}", role_key="owner")
    context = context_from_membership(Membership.objects.get(organization=organization, user=user))
    with _as(context):
        site = create_site(
            name="Teksty",
            slug=f"t-{uuid7().hex[-12:]}",
            default_locale="pl",
            idempotency_key=_key(),
        ).value
        home_page(site.id)
        appearance = default_appearance(site)
        appearance["footer"] = {
            "layout": "simple",
            "text": "Zapraszamy",
            "links": [{"label": "Kontakt", "href": "/kontakt/"}],
        }
        save_site_appearance(
            site_id=site.id, expected_version=0, appearance=appearance, idempotency_key=_key()
        )
        publish_site(site_id=site.id, idempotency_key=_key())

    read = client.get(f"/api/v1/sites/{site.id}/texts/en/")
    assert read.status_code == 200, read.data
    assert [(item["role"], item["state"]) for item in read.data["items"]] == [
        ("footer", "missing"),
        ("footer_link", "missing"),
    ]
    saved = client.put(
        f"/api/v1/sites/{site.id}/texts/en/",
        {
            "expected_version": read.data["version"],
            "texts": {read.data["items"][0]["key"]: "Welcome"},
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert saved.status_code == 200, saved.data
    assert saved.data["items"][0]["text"] == "Welcome"
    stale = client.put(
        f"/api/v1/sites/{site.id}/texts/en/",
        {"expected_version": read.data["version"], "texts": {"footer/text": "Hello"}},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert stale.status_code == 409
    published = client.post(
        f"/api/v1/sites/{site.id}/texts/en/publish/",
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=_key(),
    )
    assert published.status_code == 200, published.data
    snapshot = Site.all_objects.get(pk=site.id).current_publication.snapshot
    assert snapshot["site_texts"] == {"en": {"footer/text": "Welcome"}}


def test_a_publication_without_new_texts_is_not_notified():
    driver = SiteTextsDriver()
    site = driver.create(["Kontakt"])
    driver.publish(site)

    with captured_source_changes() as notices:
        driver.move(site, 0, 0)
        driver.publish(site)

    assert notices == []
