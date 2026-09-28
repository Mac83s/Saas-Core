"""Ustawienia › Usługi i grafik (team phase 3c): the catalogue as the office
edits it — services with who does them, where and with what, and the places
and resources, switched-off ones included, which the calendar's catalogue
hides. People and their hours live in Zespół, not here (ADR-058 §1).

Editing never touches booked visits: a visit keeps its service name, its
people and the number of people it was booked with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils.text import slugify
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import (
    audit_snapshot,
    field_changes,
    record_audit,
)
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.models import Organization, OrganizationAuditAction
from saas_core.modules.shared.billing.authorization import authorize_entitled

from . import materials as stock
from .models import (
    Location,
    PublicBookingRoute,
    Resource,
    Service,
    ServiceLocation,
    ServiceResource,
    ServiceStaff,
    StaffChoice,
    StaffMember,
)
from .services import BOOKING_ENABLED, BOOKING_MANAGE, _assert_appointment_kind_available

#: What the history keeps of a service; the links go in as counts.
_SERVICE_FIELDS = (
    "name",
    "duration_minutes",
    "buffer_before_minutes",
    "buffer_after_minutes",
    "minimum_notice_minutes",
    "staff_count",
    "public_staff_choice",
    "active",
)
_PLACE_FIELDS = ("name", "address", "active")
_RESOURCE_FIELDS = ("name", "active")
# `slugify` drops what NFKD cannot fold: "Łódź" would become "odz".
_FOLD = str.maketrans({"ł": "l", "Ł": "L"})


@dataclass(frozen=True, slots=True)
class ServiceSetup:
    service: Service
    staff_ids: list[UUID] = field(default_factory=list)
    location_ids: list[UUID] = field(default_factory=list)
    resource_ids: list[UUID] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Setup:
    services: list[ServiceSetup]
    locations: list[Location]
    resources: list[Resource]
    #: Who can be named as a performer: the company's current people.
    staff: list[StaffMember]


def _manage() -> tuple[TenantContext, Organization]:
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED)
    return context, Organization.objects.get(pk=context.organization_id)


def list_setup() -> Setup:
    _, organization = _manage()
    links: dict[UUID, dict[str, list[UUID]]] = {}
    sources: tuple[tuple[type[Any], str, str, dict[str, Any]], ...] = (
        (ServiceStaff, "staff", "staff_id", {}),
        (ServiceLocation, "locations", "location_id", {}),
        (ServiceResource, "resources", "resource_id", {"required": True}),
    )
    for model, key, column, extra in sources:
        rows = model.all_objects.filter(organization=organization, **extra).order_by("id")
        for service_id, target in rows.values_list("service_id", column):
            links.setdefault(service_id, {}).setdefault(key, []).append(target)
    services = Service.all_objects.filter(organization=organization)
    return Setup(
        services=[
            ServiceSetup(
                service,
                links.get(service.id, {}).get("staff", []),
                links.get(service.id, {}).get("locations", []),
                links.get(service.id, {}).get("resources", []),
            )
            for service in services
        ],
        locations=list(Location.all_objects.filter(organization=organization)),
        resources=list(Resource.all_objects.filter(organization=organization)),
        staff=list(StaffMember.all_objects.filter(organization=organization, active=True)),
    )


def _free_slug(model: type[Any], organization: Organization, name: str) -> str:
    base = slugify(name.translate(_FOLD))[:72] or "pozycja"
    slug, number = base, 1
    taken = model.all_objects.filter(organization=organization)
    while taken.filter(public_slug=slug).exists():
        number += 1
        slug = f"{base}-{number}"
    return slug


def _own(model: type[Any], organization: Organization, ids: list[UUID], name: str) -> list[UUID]:
    """The ids once each, all of them the company's own — or a refusal."""
    wanted = list(dict.fromkeys(ids))
    found = model.all_objects.filter(organization=organization, pk__in=wanted)
    if model is StaffMember:
        found = found.filter(active=True)
    if found.count() != len(wanted):
        raise ValidationError({name: "Nie ma takiej pozycji."})
    return wanted


def _relink(
    model: type[Any],
    organization: Organization,
    service: Service,
    column: str,
    wanted: list[UUID],
    **extra: Any,
) -> bool:
    """Makes the service's links exactly `wanted`; says whether anything moved."""
    rows = model.all_objects.filter(organization=organization, service=service, **extra)
    current = set(rows.values_list(column, flat=True))
    gone = current - set(wanted)
    if gone:
        rows.filter(**{f"{column}__in": gone}).delete()
    added = [target for target in wanted if target not in current]
    model.all_objects.bulk_create([
        model(organization=organization, service=service, **{column: target}, **extra)
        for target in added
    ])
    return bool(gone or added)


def _audit(
    organization: Organization,
    context: TenantContext,
    target_type: str,
    target_id: UUID,
    changes: dict[str, Any],
    created: bool,
) -> None:
    if not changes and not created:
        return
    record_audit(
        organization=organization,
        action=OrganizationAuditAction.BOOKING_CATALOG_CHANGED,
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type=target_type,
        target_id=target_id,
        metadata={"changes": changes} if changes else {"created": True},
    )


@transaction.atomic
def save_service(*, service_id: UUID | None, data: dict[str, Any]) -> ServiceSetup:
    """Creates a service or changes one, with its people, places and resource.

    `staff_ids`, `location_ids` and `resource_ids`, when given, replace the
    links; `materials` replaces what each visit takes from the warehouse.
    """
    context, organization = _manage()
    values = dict(data)
    staff_ids = values.pop("staff_ids", None)
    location_ids = values.pop("location_ids", None)
    resource_ids = values.pop("resource_ids", None)
    materials = values.pop("materials", None)
    if service_id is None:
        _assert_appointment_kind_available(organization, values.get("appointment_kind", ""))
        service = Service(
            organization=organization,
            public_slug=_free_slug(Service, organization, values.get("name", "")),
            **values,
        )
        before: dict[str, Any] = {}
    else:
        values.pop("appointment_kind", None)
        found = (
            Service.all_objects.select_for_update()
            .filter(organization=organization, pk=service_id)
            .first()
        )
        if found is None:
            raise NotFound("Nie ma takiej usługi.")
        service = found
        before = audit_snapshot(service, _SERVICE_FIELDS)
        for name, value in values.items():
            setattr(service, name, value)
    if service.public_staff_choice == StaffChoice.PERSON and service.staff_count != 1:
        raise ValidationError({
            "public_staff_choice": "Osobę klient wybiera tylko przy usłudze dla jednej osoby."
        })
    service.save()
    changes = field_changes(before, audit_snapshot(service, _SERVICE_FIELDS)) if before else {}
    for key, name, target, model, column, extra, ids in (
        ("performers", "staff_ids", StaffMember, ServiceStaff, "staff_id", {}, staff_ids),
        ("locations", "location_ids", Location, ServiceLocation, "location_id", {}, location_ids),
        (
            "resources",
            "resource_ids",
            Resource,
            ServiceResource,
            "resource_id",
            {"required": True},
            resource_ids,
        ),
    ):
        if ids is None:
            continue
        wanted = _own(target, organization, ids, name)
        if _relink(model, organization, service, column, wanted, **extra) and before:
            changes[key] = {"changed": True}
    if materials is not None:
        if materials:
            stock.authorize_change()
            stock.refuse_own(service.appointment_kind)
        lines = stock.normalize(organization.id, materials)
        stored = [
            {"item_id": line["item_id"], "quantity": line["quantity"], "mode": line["mode"]}
            for line in lines
        ]
        if stored != service.materials:
            service.materials = stored
            service.save(update_fields=["materials", "updated_at"])
            if before:
                changes["materials"] = {"changed": True}
    # The public form finds the company by its slug from the first service on.
    PublicBookingRoute.objects.get_or_create(
        public_slug=organization.slug, defaults={"organization_id": organization.id}
    )
    _audit(organization, context, "service", service.id, changes, created=not before)
    links = {
        column: list(
            model.all_objects.filter(organization=organization, service=service, **extra)
            .order_by("id")
            .values_list(column, flat=True)
        )
        for model, column, extra in (
            (ServiceStaff, "staff_id", {}),
            (ServiceLocation, "location_id", {}),
            (ServiceResource, "resource_id", {"required": True}),
        )
    }
    return ServiceSetup(service, links["staff_id"], links["location_id"], links["resource_id"])


@transaction.atomic
def save_location(*, location_id: UUID | None, data: dict[str, Any]) -> Location:
    context, organization = _manage()
    if location_id is None:
        location = Location(
            organization=organization,
            public_slug=_free_slug(Location, organization, data.get("name", "")),
            **data,
        )
        before: dict[str, Any] = {}
    else:
        found = (
            Location.all_objects.select_for_update()
            .filter(organization=organization, pk=location_id)
            .first()
        )
        if found is None:
            raise NotFound("Nie ma takiego miejsca.")
        location = found
        before = audit_snapshot(location, _PLACE_FIELDS)
        for name, value in data.items():
            setattr(location, name, value)
    location.save()
    changes = (
        field_changes(before, audit_snapshot(location, _PLACE_FIELDS), private=("address",))
        if before
        else {}
    )
    _audit(organization, context, "location", location.id, changes, created=not before)
    return location


@transaction.atomic
def save_resource(*, resource_id: UUID | None, data: dict[str, Any]) -> Resource:
    context, organization = _manage()
    if resource_id is None:
        resource = Resource(organization=organization, **data)
        before: dict[str, Any] = {}
    else:
        found = (
            Resource.all_objects.select_for_update()
            .filter(organization=organization, pk=resource_id)
            .first()
        )
        if found is None:
            raise NotFound("Nie ma takiego zasobu.")
        resource = found
        before = audit_snapshot(resource, _RESOURCE_FIELDS)
        for name, value in data.items():
            setattr(resource, name, value)
    resource.save()
    changes = field_changes(before, audit_snapshot(resource, _RESOURCE_FIELDS)) if before else {}
    _audit(organization, context, "resource", resource.id, changes, created=not before)
    return resource
