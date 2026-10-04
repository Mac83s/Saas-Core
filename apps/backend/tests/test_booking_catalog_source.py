"""`booking.catalog` keeps the translation source contract (ADR-069, plan
TL12c; `docs/architecture/translation-sources.md` §11), plus what only the
booking catalogue does: a changed service sends only its own unit, a switched
off or deleted item leaves the catalogue, a team's name is a proper name, and
a visit keeps the service's name in the customer's language. Needs no
translation engine (the contract plays it); the product profiles compose
booking without it.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import time, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
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
from saas_core.content_protocol.units import UNIT_NAME, UNIT_TEXT, sendable_units
from saas_core.modules.core.organizations.context import (
    TenantContext,
    acting_context,
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.shared.booking.item_translations import (
    apply_item_translation,
    save_item_translation,
    translatable,
)
from saas_core.modules.shared.booking.models import (
    Appointment,
    PublicBookingRoute,
    Resource,
    ResourceTranslation,
    Service,
    StaffTeam,
)
from saas_core.modules.shared.booking.services import BOOKING_MANAGE
from saas_core.modules.shared.booking.setup import save_service
from saas_core.modules.shared.booking.translation_source import (
    CATALOG_SOURCE,
    catalog,
    notify_catalog_changed,
)
from saas_core.testing.translation_sources import TranslationSourceContract, UnitSpec
from test_booking import company_today, membership, tenant
from test_booking_slots import team
from test_team_people import bookable

pytestmark = pytest.mark.django_db


@contextmanager
def _as(context: TenantContext) -> Iterator[None]:
    with transaction.atomic():
        set_local_organization_id(context.organization_id)
        with activate_tenant_context(context):
            yield


@pytest.fixture(autouse=True)
def german_on_the_platform() -> Iterator[None]:
    cache.clear()
    with override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de")):
        yield


class BookingCatalogDriver:
    """The scenario's units are units of the company's catalogue (resources by
    name), a `name` unit a team; the object is the company itself."""

    source = CATALOG_SOURCE
    capabilities = frozenset({"placeholder", "name", "unordered", "single_object"})

    def __init__(self) -> None:
        owner = membership(f"catalog-source-{uuid4().hex[:10]}")
        organization = owner.organization
        organization.public_locales = ["pl", "de"]
        organization.save(update_fields=["public_locales"])
        bookable(organization)
        PublicBookingRoute.objects.create(
            public_slug=organization.slug, organization_id=organization.id
        )
        self.organization = organization
        self.publisher = context_from_membership(owner)
        self.editor = replace(
            self.publisher, permissions=self.publisher.permissions - {BOOKING_MANAGE}
        )

    def acting(self, context: TenantContext) -> TenantContext:
        return acting_context(context, via="ai_translation", ref=f"translation_job:{uuid4()}")

    def _add(self, unit: str | UnitSpec) -> None:
        text = unit.text if isinstance(unit, UnitSpec) else unit
        if isinstance(unit, UnitSpec) and unit.kind == UNIT_NAME:
            StaffTeam.all_objects.create(organization=self.organization, name=text)
        else:
            Resource.all_objects.create(organization=self.organization, name=text)

    def create(self, units: Sequence[str | UnitSpec], *, legal: bool = False) -> UUID:
        with _as(self.publisher):
            for unit in units:
                self._add(unit)
        return self.organization.id

    def _resources(self) -> list[Resource]:
        return [
            item for _e, item, _u in catalog(self.organization.id) if isinstance(item, Resource)
        ]

    def insert(self, object_id: UUID, index: int, text: str) -> None:
        with _as(self.publisher):
            self._add(text)

    def move(self, object_id: UUID, from_index: int, to_index: int) -> None:
        raise NotImplementedError("A catalogue has no positions.")

    def edit(self, object_id: UUID, index: int, text: str) -> None:
        with _as(self.publisher):
            resource = self._resources()[index]
            Resource.all_objects.filter(pk=resource.pk).update(name=text)

    def delete(self, object_id: UUID, index: int) -> None:
        with _as(self.publisher):
            self._resources()[index].delete()

    def publish(self, object_id: UUID) -> None:
        with _as(self.publisher):
            notify_catalog_changed(context=self.publisher)

    def _write(self, index: int, locale: str, text: str, provenance: Provenance) -> None:
        with _as(self.publisher):
            resource = self._resources()[index]
            apply_item_translation(
                translatable("resource"),
                resource,
                locale,
                {"name": (text, provenance)},
                actor_id=self.publisher.actor_id,
            )

    def write_as_person(self, object_id: UUID, locale: str, index: int, text: str) -> None:
        with _as(self.publisher):
            resource = self._resources()[index]
            row = ResourceTranslation.all_objects.filter(resource=resource, locale=locale).first()
            save_item_translation(
                kind="resource",
                item_id=resource.id,
                locale=locale,
                texts={"name": text},
                expected_version=row.version if row else 0,
                idempotency_key=str(uuid4()),
            )

    def write_as_integration(self, object_id: UUID, locale: str, index: int, text: str) -> None:
        resource = self._resources()[index]
        provenance = Provenance(
            origin=ORIGIN_INTEGRATION,
            source_hash=unit_hash(UNIT_TEXT, resource.name),
            written_hash=unit_hash(UNIT_TEXT, text),
        )
        self._write(index, locale, text, provenance)

    def copy_source(self, object_id: UUID, locale: str) -> None:
        for index, resource in enumerate(self._resources()):
            copied = Provenance(origin=ORIGIN_COPY, source_hash=unit_hash(UNIT_TEXT, resource.name))
            self._write(index, locale, resource.name, copied)

    def public_texts(self, object_id: UUID, locale: str) -> list[str] | None:
        """The public form's units in the language; None while the catalogue
        has no translation of its own in it."""
        cache.clear()
        answer = (
            APIClient()
            .get(f"/api/v1/booking/public/{self.organization.slug}/", {"locale": locale})
            .json()
        )
        if answer.get("locale") != locale:
            return None
        translated = {
            row.resource_id
            for row in ResourceTranslation.all_objects.filter(
                organization=self.organization, locale=locale
            )
            if (row.provenance or {}).get("name", {}).get("origin") != ORIGIN_COPY
        }
        if not translated:
            return None
        return [str(item["name"]) for item in answer["resources"]]


class TestBookingCatalogSource(TranslationSourceContract):
    source_key = "booking.catalog"

    @pytest.fixture
    def driver(self) -> BookingCatalogDriver:
        return BookingCatalogDriver()


# -- what only the booking catalogue does --------------------------------------


def _company(slug: str) -> dict[str, Any]:
    owner = membership(slug)
    organization = owner.organization
    organization.public_locales = ["pl", "de"]
    organization.save(update_fields=["public_locales"])
    bookable(organization)
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    configured["owner"] = owner
    return configured


def _read(owner: Any, locale: str = "de") -> Any:
    with tenant(owner) as context:
        return CATALOG_SOURCE.read(
            context=context, object_id=owner.organization_id, locale=locale, basis="published"
        )


def test_units_are_grouped_by_item_and_a_teams_name_is_a_proper_name() -> None:
    configured = _company("tl12c-units")
    owner = configured["owner"]
    with tenant(owner):
        crew = StaffTeam.all_objects.create(organization=owner.organization, name="Ekipa A")
    read = _read(owner)
    keys = [unit.key for unit in read.units]
    assert keys == [
        f"location/{configured['location'].id}/name",
        f"service/{configured['service'].id}/name",
        f"team/{crew.id}/name",
    ]
    team_unit = read.units[-1]
    assert team_unit.kind == UNIT_NAME
    sent = sendable_units(read.units, read.targets, sendable={"public"}, protected="propose")
    assert f"team/{crew.id}/name" not in {unit.key for unit in sent.units}


def test_renaming_one_service_sends_only_its_own_name() -> None:
    configured = _company("tl12c-rename")
    owner = configured["owner"]
    with tenant(owner):
        second = Service.all_objects.create(
            organization=owner.organization, name="Masaż", public_slug="masaz", duration_minutes=30
        )
    read = _read(owner)
    with tenant(owner) as context:
        written = {
            unit.key: (f"[de] {unit.text}", Provenance("ai", unit.source_hash))
            for unit in read.units
        }
        _write_all(context, read, written)
        save_service(
            service_id=second.id,
            data={"name": "Masaż relaksacyjny"},
            expected_version=second.version,
            idempotency_key=str(uuid4()),
        )
    after = _read(owner)
    selection = sendable_units(after.units, after.targets, sendable={"public"}, protected="propose")
    assert [unit.key for unit in selection.units] == [f"service/{second.id}/name"]


def _write_all(context: TenantContext, read: Any, texts: dict[str, Any]) -> None:
    from saas_core.content_protocol.policy import Trigger
    from saas_core.content_protocol.sources import WriteBatch, WriteItem
    from saas_core.testing.translation_sources import AUTOMATIC, translation_policy_override

    with translation_policy_override(AUTOMATIC):
        CATALOG_SOURCE.write(
            context=context,
            batch=WriteBatch(
                source_key="booking.catalog",
                scope=read.scope,
                trigger=Trigger(kind="click", job_ref=f"translation_job:{uuid4()}", cause="user"),
                protected="propose",
                items=(
                    WriteItem(
                        object_id=read.object_id,
                        locale="de",
                        basis="published",
                        basis_version=read.basis_version,
                        target_version=read.target_version,
                        texts=texts,
                        requested="live",
                    ),
                ),
                idempotency_key=str(uuid4()),
            ),
        )


def test_a_switched_off_or_deleted_item_leaves_the_catalogue() -> None:
    configured = _company("tl12c-gone")
    owner = configured["owner"]
    service = configured["service"]
    PublicBookingRoute.objects.create(
        public_slug="tl12c-gone", organization_id=owner.organization_id
    )
    with tenant(owner):
        save_item_translation(
            kind="service",
            item_id=service.id,
            locale="de",
            texts={"name": "Termin"},
            expected_version=0,
            idempotency_key=str(uuid4()),
        )
        save_service(
            service_id=service.id,
            data={"active": False},
            expected_version=service.version,
            idempotency_key=str(uuid4()),
        )
    assert f"service/{service.id}/name" not in {unit.key for unit in _read(owner).units}
    german = APIClient().get("/api/v1/booking/public/tl12c-gone/", {"locale": "de"}).json()
    assert german["services"] == []
    # A unit taken out of the catalogue takes its translations along.
    with tenant(owner):
        chair = Resource.all_objects.create(organization=owner.organization, name="Fotel")
        save_item_translation(
            kind="resource",
            item_id=chair.id,
            locale="de",
            texts={"name": "Sessel"},
            expected_version=0,
            idempotency_key=str(uuid4()),
        )
        chair.delete()
    assert not ResourceTranslation.all_objects.filter(resource_id=chair.id).exists()
    assert f"resource/{chair.id}/name" not in {unit.key for unit in _read(owner).units}


def test_a_visit_keeps_the_service_in_the_customers_language_and_older_ones_fall_back() -> None:
    configured = _company("tl12c-visit")
    owner = configured["owner"]
    service = configured["service"]
    PublicBookingRoute.objects.create(
        public_slug="tl12c-visit", organization_id=owner.organization_id
    )
    with tenant(owner):
        save_item_translation(
            kind="service",
            item_id=service.id,
            locale="de",
            texts={"name": "Termin"},
            expected_version=0,
            idempotency_key=str(uuid4()),
        )
    url = "/api/v1/booking/public/tl12c-visit"
    day = company_today() + timedelta(days=7)
    query = {"service_id": str(service.id), "location_id": str(configured["location"].id)}
    client = APIClient()
    times = client.get(f"{url}/times/", {**query, "date": day.isoformat()}).json()["items"]
    booked = client.post(
        f"{url}/appointments/",
        {
            **query,
            "starts_at": times[0]["starts_at"],
            "customer": {"display_name": "Anna", "email": "anna@example.test", "locale": "de"},
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert booked.status_code == 201, booked.data
    assert booked.json()["service_name"] == "Termin"  # what the .ics file says
    visit = Appointment.all_objects.get(pk=booked.json()["id"])
    assert (visit.service_name, visit.customer_service_name) == ("Wizyta", "Termin")
    # A visit from before TL12c: the name it was booked with, the company's.
    Appointment.all_objects.filter(pk=visit.pk).update(customer_service_name="")
    from saas_core.modules.shared.booking.security import public_booking_context
    from saas_core.modules.shared.booking.views import _public_appointment_payload

    visit.refresh_from_db()
    # As the customer's link reads it: inside the company it names.
    with public_booking_context(visit.organization_id):
        assert _public_appointment_payload(visit)["service_name"] == "Wizyta"
