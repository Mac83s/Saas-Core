"""`profiles.public_profile` keeps the translation source contract (ADR-069,
plan TL12a; `docs/architecture/translation-sources.md` §11), plus what only
business cards do: the catalogue in another language, a person's card under
`public_personal`, the version lock of a person's translation.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid7

import pytest
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.test import override_settings
from rest_framework.test import APIClient

from saas_core.content_protocol.provenance import (
    ORIGIN_COPY,
    ORIGIN_INTEGRATION,
    Provenance,
    unit_hash,
)
from saas_core.content_protocol.units import UNIT_TEXT, sendable_units
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
from saas_core.modules.shared.profiles.card_languages import card_in_language
from saas_core.modules.shared.profiles.catalog import publish_profile
from saas_core.modules.shared.profiles.catalog_contract import categories
from saas_core.modules.shared.profiles.models import (
    CatalogEntry,
    ProfileSubjectKind,
    PublicProfile,
    PublicProfileTranslation,
)
from saas_core.modules.shared.profiles.permissions import PROFILES_MANAGE
from saas_core.modules.shared.profiles.services import (
    create_profile,
    organization_profile,
    save_translation,
    update_profile,
)
from saas_core.modules.shared.profiles.translation_source import (
    BIO,
    HEADLINE,
    PROFILE_SOURCE,
    apply_translation,
    link_key,
    notify_card_changed,
    source_units,
)
from saas_core.testing.translation_sources import TranslationSourceContract, UnitSpec

pytestmark = pytest.mark.django_db


@contextmanager
def _as(context: TenantContext) -> Iterator[None]:
    with transaction.atomic():
        set_local_organization_id(context.organization_id)
        with activate_tenant_context(context):
            yield


def _text(unit: str | UnitSpec) -> str:
    return unit.text if isinstance(unit, UnitSpec) else unit


class ProfilesDriver:
    """The first object is the company's card, in the catalogue; any further
    one is a person's card of the same company. The scenario's units are the
    card's link labels; its headline and bio are the card's own units, sent
    and written but not compared."""

    source = PROFILE_SOURCE
    capabilities = frozenset({"placeholder"})
    extra_unit_keys = frozenset({HEADLINE, BIO})

    def __init__(self) -> None:
        user = User.objects.create_user(email=f"card-source-{uuid7()}@example.test")
        user.status = UserStatus.ACTIVE
        user.save()
        self.organization = Organization.objects.create(
            name="Studio Wizytówka",
            slug=f"wizytowka-{uuid7().hex[-12:]}",
            status=OrganizationStatus.ACTIVE,
            public_locales=["pl", "de"],
        )
        EntitlementSnapshot.all_objects.create(
            organization=self.organization,
            subscription_state=SubscriptionState.ACTIVE,
            access_mode=AccessMode.FULL,
            features={"profiles.enabled": True},
            sources={"profiles.enabled": {"kind": "plan"}},
        )
        membership = Membership.objects.create(
            organization=self.organization,
            user=user,
            role=Role.objects.get(key="owner", organization=None, organization_type=""),
        )
        self.publisher = context_from_membership(membership)
        self.editor = replace(
            self.publisher, permissions=self.publisher.permissions - {PROFILES_MANAGE}
        )
        self.company: UUID | None = None

    def acting(self, context: TenantContext) -> TenantContext:
        return acting_context(context, via="ai_translation", ref=f"translation_job:{uuid7()}")

    # -- the card's source

    def create(self, units: Sequence[str | UnitSpec], *, legal: bool = False) -> UUID:
        links = [
            {"label": _text(unit), "url": f"https://example.test/{uuid7().hex}"} for unit in units
        ]
        with _as(self.publisher):
            if self.company is None:
                profile = organization_profile()
                profile = update_profile(
                    profile.id,
                    expected_version=profile.version,
                    headline="Fryzjer w centrum",
                    bio="Strzyżemy od 1990 roku.",
                    links=links,
                    city_slug="mragowo",
                    category=next(iter(categories(settings.DEFAULT_ORGANIZATION_TYPE))),
                )
                self.company = profile.id
                return profile.id
            person = create_profile(
                subject_kind=ProfileSubjectKind.PERSON,
                display_name="Anna Nowak",
                headline="Stylistka",
                bio="Koloryzacja i strzyżenie.",
                links=links,
            )
            return person.id

    def _links(self, object_id: UUID) -> list[dict[str, str]]:
        return list(PublicProfile.all_objects.get(pk=object_id).links)

    def _change(self, object_id: UUID, change: Any) -> None:
        links = self._links(object_id)
        change(links)
        with _as(self.publisher):
            profile = PublicProfile.all_objects.get(pk=object_id)
            update_profile(object_id, expected_version=profile.version, links=links)

    def insert(self, object_id: UUID, index: int, text: str) -> None:
        self._change(
            object_id,
            lambda links: links.insert(
                index, {"label": text, "url": f"https://example.test/{uuid7().hex}"}
            ),
        )

    def move(self, object_id: UUID, from_index: int, to_index: int) -> None:
        self._change(object_id, lambda links: links.insert(to_index, links.pop(from_index)))

    def edit(self, object_id: UUID, index: int, text: str) -> None:
        def change(links: list[dict[str, str]]) -> None:
            links[index] = {**links[index], "label": text}

        self._change(object_id, change)

    def delete(self, object_id: UUID, index: int) -> None:
        self._change(object_id, lambda links: links.pop(index))

    def publish(self, object_id: UUID) -> None:
        with _as(self.publisher):
            if object_id == self.company:
                publish_profile()
            else:
                notify_card_changed(context=self.publisher, profile_id=object_id)

    # -- the language's text

    def _key(self, object_id: UUID, index: int) -> str:
        return link_key(self._links(object_id)[index]["url"])

    def _version(self, object_id: UUID, locale: str) -> int:
        row = PublicProfileTranslation.all_objects.filter(
            profile_id=object_id, locale=locale
        ).first()
        return row.version if row is not None else 0

    def write_as_person(self, object_id: UUID, locale: str, index: int, text: str) -> None:
        with _as(self.publisher):
            save_translation(
                object_id,
                locale=locale,
                expected_version=self._version(object_id, locale),
                link_labels={self._key(object_id, index): text},
            )

    def _write(
        self, object_id: UUID, locale: str, texts: dict[str, tuple[str, Provenance]]
    ) -> None:
        with _as(self.publisher):
            profile = PublicProfile.all_objects.get(pk=object_id)
            apply_translation(profile, locale, texts, actor_id=self.publisher.actor_id)

    def write_as_integration(self, object_id: UUID, locale: str, index: int, text: str) -> None:
        unit = next(u for u in self._units(object_id) if u.key == self._key(object_id, index))
        provenance = Provenance(
            origin=ORIGIN_INTEGRATION,
            source_hash=unit.source_hash,
            written_hash=unit_hash(UNIT_TEXT, text),
        )
        self._write(object_id, locale, {unit.key: (text, provenance)})

    def copy_source(self, object_id: UUID, locale: str) -> None:
        self._write(
            object_id,
            locale,
            {
                unit.key: (unit.text, Provenance(origin=ORIGIN_COPY, source_hash=unit.source_hash))
                for unit in self._units(object_id)
            },
        )

    def _units(self, object_id: UUID) -> list[Any]:
        return list(source_units(PublicProfile.all_objects.get(pk=object_id)))

    def public_texts(self, object_id: UUID, locale: str) -> list[str] | None:
        """The link labels the card shows in the language, unit by unit — a
        person's card from its row; the company's while it is in the
        catalogue. Whether the catalogue serves the card in the language at
        all (every text translated, TL20) is `test_profiles_catalog_languages`."""
        if (
            object_id == self.company
            and not CatalogEntry.all_objects.filter(profile_id=object_id).exists()
        ):
            return None
        row = PublicProfileTranslation.all_objects.filter(
            profile_id=object_id, locale=locale
        ).first()
        if row is None:
            return None
        shown = card_in_language(PublicProfile.all_objects.get(pk=object_id), row)
        if any(key.startswith("link/") for key in shown["fallback"]):
            return None
        return [str(link["label"]) for link in shown["links"]]


@pytest.fixture(autouse=True)
def german_on_the_platform() -> Iterator[None]:
    with override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de")):
        yield


class TestProfilesSource(TranslationSourceContract):
    source_key = "profiles.public_profile"

    @pytest.fixture
    def driver(self) -> ProfilesDriver:
        return ProfilesDriver()


# -- what only business cards do ----------------------------------------------


def test_the_catalogue_serves_the_card_in_german_only_whole() -> None:
    driver = ProfilesDriver()
    card = driver.create(["Cennik"])
    driver.publish(card)
    with _as(driver.publisher):
        save_translation(
            card,
            locale="de",
            expected_version=0,
            headline="Friseur im Zentrum",
            allow_bio_fallback=False,
        )
    entry = CatalogEntry.all_objects.get(profile_id=card)
    url = f"/api/v1/public/catalog/{entry.city_slug}/{entry.slug}/"
    cache.clear()
    # Bio and the link are still Polish: the card stays Polish, never a mix (TL20).
    half = APIClient().get(url, {"locale": "de"}).data
    assert (half["locale"], half["headline"], half["fallback"]) == ("pl", "Fryzjer w centrum", [])
    links = PublicProfile.all_objects.get(pk=card).links
    with _as(driver.publisher):
        save_translation(
            card,
            locale="de",
            expected_version=1,
            bio="Wir schneiden seit 1990.",
            link_labels={link_key(links[0]["url"]): "Preise"},
        )
    cache.clear()
    german = APIClient().get(url, {"locale": "de"}).data
    assert (german["locale"], german["headline"], german["bio"]) == (
        "de",
        "Friseur im Zentrum",
        "Wir schneiden seit 1990.",
    )
    assert (german["links"][0]["label"], german["fallback"]) == ("Preise", [])
    assert german["translated_locales"] == ["de"]
    # A language the company does not have: the card's own.
    assert APIClient().get(url, {"locale": "es"}).data["locale"] == "pl"
    assert APIClient().get(url).data["headline"] == "Fryzjer w centrum"


def test_a_persons_card_reaches_a_model_only_where_the_deployment_lists_it() -> None:
    driver = ProfilesDriver()
    driver.create(["Cennik"])
    person = driver.create(["Portfolio"])
    with _as(driver.publisher):
        read = PROFILE_SOURCE.read(
            context=driver.publisher, object_id=person, locale="de", basis="published"
        )
    assert {unit.data_class for unit in read.units} == {"public_personal"}
    # The person's name is never a unit; it is a protected term instead.
    assert all("Anna Nowak" not in unit.text for unit in read.units)
    assert [
        t.text for t in PROFILE_SOURCE.protected_terms(context=driver.publisher, object_id=person)
    ] == ["Anna Nowak"]
    public_only = sendable_units(read.units, read.targets, sendable={"public"}, protected="propose")
    assert public_only.units == ()
    listed = sendable_units(
        read.units, read.targets, sendable={"public", "public_personal"}, protected="propose"
    )
    assert {unit.key for unit in listed.units} == {
        HEADLINE,
        BIO,
        link_key(PublicProfile.all_objects.get(pk=person).links[0]["url"]),
    }
