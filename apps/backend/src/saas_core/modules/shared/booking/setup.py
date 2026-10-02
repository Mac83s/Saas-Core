"""Ustawienia › Usługi i grafik (team phase 3c): the catalogue as the office
edits it — services with who does them, where and with what, and the places
and resources, switched-off ones included, which the calendar's catalogue
hides. People and their hours live in Zespół, not here (ADR-058 §1).

Editing never touches booked visits: a visit keeps its service name, its
people and the number of people it was booked with.

Every write here is a setup write (ADR-072 §11): it carries an idempotency key,
whose receipt is a `BookingSetupMutation`, changes an item only at the version
its caller saw (409 `booking_version_conflict`), and runs as a preview with
nothing saved — the same code in a savepoint that is rolled back, so a preview
refuses exactly what the write would. The panel and the assistant's commands
call these same functions.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.utils.text import slugify
from rest_framework.exceptions import NotFound, ParseError, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import (
    audit_snapshot,
    field_changes,
    record_audit,
)
from saas_core.modules.core.organizations.canonical import canonical_json_hash
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.models import Organization, OrganizationAuditAction
from saas_core.modules.shared.billing.authorization import authorize_entitled
from saas_core.modules.shared.billing.decisions import FeatureOperation

from . import materials as stock
from .models import (
    BookingSetupMutation,
    Location,
    PublicBookingRoute,
    Resource,
    ResourceGroup,
    Service,
    ServiceLocation,
    ServiceResource,
    ServiceStaff,
    StaffChoice,
    StaffMember,
)
from .offer_settings import offer_options
from .services import (
    BOOKING_ENABLED,
    BOOKING_MANAGE,
    BookingIdempotencyConflict,
    BookingVersionConflict,
    _assert_appointment_kind_available,
)

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
_RESOURCE_FIELDS = ("name", "active", "capacity", "description", "group_id", "location_id")
_GROUP_FIELDS = ("name", "description", "active")
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
    #: Pools of identical units (ADR-072 §3).
    groups: list[ResourceGroup]
    #: Who can be named as a performer: the company's current people.
    staff: list[StaffMember]


@dataclass(frozen=True, slots=True)
class Saved[T]:
    """What a setup write answers (ADR-072 §11)."""

    value: T
    item_id: UUID
    #: The item's version after the write — for a preview, after it would be.
    version: int
    created: bool
    #: What changed, as the history keeps it (`{field: {"from", "to"}}`);
    #: empty for a new item, for a write that changed nothing and for a
    #: repeated key.
    changes: dict[str, Any] = field(default_factory=dict)
    #: The first answer of this key again: nothing was written now.
    replayed: bool = False


class _Previewed(Exception):
    """Carries a preview's answer out of the savepoint it rolls back."""

    def __init__(self, saved: Saved[Any]) -> None:
        super().__init__()
        self.saved = saved


def setup_write[T](
    *,
    context: TenantContext,
    action: str,
    target_id: UUID | None,
    request: Mapping[str, Any],
    idempotency_key: str,
    preview: bool,
    write: Callable[[], Saved[T]],
    replay: Callable[[UUID], Saved[T]],
) -> Saved[T]:
    """One setup write under its key: the first answer again for a repeated
    key, 409 `booking_idempotency_conflict` for a key reused on another
    request, and with `preview` the same write rolled back. The receipt is
    written only after the write succeeded, so a refused request may be fixed
    and sent again with its key."""
    if preview:
        try:
            with transaction.atomic():
                raise _Previewed(write())
        except _Previewed as done:
            return done.saved
    key = idempotency_key.strip()
    if not key or len(key) > 160:
        raise ParseError("Wymagany jest prawidłowy Idempotency-Key.")
    principal_ref = str(context.actor_id)
    request_hash = canonical_json_hash(
        json.loads(
            json.dumps({"action": action, "target_id": target_id, **request}, cls=DjangoJSONEncoder)
        )
    )
    with connection.cursor() as cursor:
        # One key at a time: a retry sent while the first request still runs
        # waits for it and finds its item, instead of creating a second one
        # and failing on the receipt's index.
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"booking-setup:{context.organization_id}:{principal_ref}:{action}:{key}"],
        )
    receipt = BookingSetupMutation.all_objects.filter(
        organization_id=context.organization_id,
        action=action,
        principal_ref=principal_ref,
        idempotency_key=key,
    ).first()
    if receipt is not None:
        if receipt.request_hash != request_hash:
            raise BookingIdempotencyConflict
        return replay(receipt.result_id)
    saved = write()
    BookingSetupMutation.all_objects.create(
        organization_id=context.organization_id,
        action=action,
        principal_ref=principal_ref,
        idempotency_key=key,
        request_hash=request_hash,
        result_kind=action.split(".", 1)[0],
        result_id=saved.item_id,
    )
    return saved


def check_version(current: int, expected: int | None) -> None:
    """A change applies to the version its caller saw, or to none."""
    if expected is None:
        raise ValidationError(
            {"expected_version": "Podaj wersję, którą zmieniasz."}, code="required"
        )
    if current != expected:
        raise BookingVersionConflict


def _manage(
    operation: FeatureOperation = FeatureOperation.WRITE,
) -> tuple[TenantContext, Organization]:
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED, operation=operation)
    return context, Organization.objects.get(pk=context.organization_id)


def list_setup() -> Setup:
    # A read: it keeps working when the plan has lapsed to read-only.
    _, organization = _manage(FeatureOperation.READ)
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
        groups=list(ResourceGroup.all_objects.filter(organization=organization)),
        staff=list(StaffMember.all_objects.filter(organization=organization, active=True)),
    )


def setup_options() -> list[dict[str, Any]]:
    """What can be set on a service, for whoever sets services up."""
    _manage(FeatureOperation.READ)
    return offer_options()


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


def _service_links(organization: Organization, service: Service) -> ServiceSetup:
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
def save_service(
    *,
    service_id: UUID | None,
    data: dict[str, Any],
    idempotency_key: str = "",
    expected_version: int | None = None,
    preview: bool = False,
) -> Saved[ServiceSetup]:
    """Creates a service or changes one, with its people, places and resource.

    `staff_ids`, `location_ids` and `resource_ids`, when given, replace the
    links; `materials` replaces what each visit takes from the warehouse. A
    change names the version it was made on (`expected_version`).
    """
    context, organization = _manage()
    created = service_id is None
    return setup_write(
        context=context,
        action="service.create" if created else "service.update",
        target_id=service_id,
        request={"data": data, "expected_version": expected_version},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _write_service(
            context, organization, service_id, dict(data), expected_version
        ),
        replay=lambda item_id: _saved_service(
            organization,
            Service.all_objects.get(organization=organization, pk=item_id),
            created=created,
            replayed=True,
        ),
    )


def _saved_service(
    organization: Organization,
    service: Service,
    *,
    created: bool,
    changes: dict[str, Any] | None = None,
    replayed: bool = False,
) -> Saved[ServiceSetup]:
    return Saved(
        _service_links(organization, service),
        service.id,
        service.version,
        created,
        changes or {},
        replayed,
    )


def _write_service(
    context: TenantContext,
    organization: Organization,
    service_id: UUID | None,
    values: dict[str, Any],
    expected_version: int | None,
) -> Saved[ServiceSetup]:
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
        check_version(found.version, expected_version)
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
    if changes:
        service.version += 1
        service.save(update_fields=["version", "updated_at"])
    # The public form finds the company by its slug from the first service on.
    PublicBookingRoute.objects.get_or_create(
        public_slug=organization.slug, defaults={"organization_id": organization.id}
    )
    _audit(organization, context, "service", service.id, changes, created=not before)
    return _saved_service(organization, service, created=not before, changes=changes)


@transaction.atomic
def save_location(
    *,
    location_id: UUID | None,
    data: dict[str, Any],
    idempotency_key: str = "",
    expected_version: int | None = None,
    preview: bool = False,
) -> Saved[Location]:
    context, organization = _manage()
    created = location_id is None
    return setup_write(
        context=context,
        action="location.create" if created else "location.update",
        target_id=location_id,
        request={"data": data, "expected_version": expected_version},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _write_location(context, organization, location_id, data, expected_version),
        replay=lambda item_id: _saved(
            Location.all_objects.get(organization=organization, pk=item_id),
            created=created,
            replayed=True,
        ),
    )


def _saved[T: (Location, Resource, ResourceGroup)](
    item: T, *, created: bool, changes: dict[str, Any] | None = None, replayed: bool = False
) -> Saved[T]:
    return Saved(item, item.id, item.version, created, changes or {}, replayed)


def _write_location(
    context: TenantContext,
    organization: Organization,
    location_id: UUID | None,
    data: dict[str, Any],
    expected_version: int | None,
) -> Saved[Location]:
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
        check_version(found.version, expected_version)
        location = found
        before = audit_snapshot(location, _PLACE_FIELDS)
        for name, value in data.items():
            setattr(location, name, value)
    changes = (
        field_changes(before, audit_snapshot(location, _PLACE_FIELDS), private=("address",))
        if before
        else {}
    )
    if changes:
        location.version += 1
    location.save()
    _audit(organization, context, "location", location.id, changes, created=not before)
    return _saved(location, created=not before, changes=changes)


@transaction.atomic
def save_resource(
    *,
    resource_id: UUID | None,
    data: dict[str, Any],
    idempotency_key: str = "",
    expected_version: int | None = None,
    preview: bool = False,
) -> Saved[Resource]:
    context, organization = _manage()
    created = resource_id is None
    return setup_write(
        context=context,
        action="resource.create" if created else "resource.update",
        target_id=resource_id,
        request={"data": data, "expected_version": expected_version},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _write_resource(context, organization, resource_id, data, expected_version),
        replay=lambda item_id: _saved(
            Resource.all_objects.get(organization=organization, pk=item_id),
            created=created,
            replayed=True,
        ),
    )


def _write_resource(
    context: TenantContext,
    organization: Organization,
    resource_id: UUID | None,
    data: dict[str, Any],
    expected_version: int | None,
) -> Saved[Resource]:
    # A unit's group and place are the company's own; null takes it out of one.
    for name, model in (("group_id", ResourceGroup), ("location_id", Location)):
        if data.get(name) is not None:
            _own(model, organization, [data[name]], name)
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
        check_version(found.version, expected_version)
        resource = found
        before = audit_snapshot(resource, _RESOURCE_FIELDS)
        for name, value in data.items():
            setattr(resource, name, value)
    changes = field_changes(before, audit_snapshot(resource, _RESOURCE_FIELDS)) if before else {}
    if changes:
        resource.version += 1
    resource.save()
    _audit(organization, context, "resource", resource.id, changes, created=not before)
    return _saved(resource, created=not before, changes=changes)


@transaction.atomic
def save_group(
    *,
    group_id: UUID | None,
    data: dict[str, Any],
    idempotency_key: str = "",
    expected_version: int | None = None,
    preview: bool = False,
) -> Saved[ResourceGroup]:
    """A pool of identical units; a unit joins it through its own `group_id`."""
    context, organization = _manage()
    created = group_id is None
    return setup_write(
        context=context,
        action="group.create" if created else "group.update",
        target_id=group_id,
        request={"data": data, "expected_version": expected_version},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _write_group(context, organization, group_id, data, expected_version),
        replay=lambda item_id: _saved(
            ResourceGroup.all_objects.get(organization=organization, pk=item_id),
            created=created,
            replayed=True,
        ),
    )


def _write_group(
    context: TenantContext,
    organization: Organization,
    group_id: UUID | None,
    data: dict[str, Any],
    expected_version: int | None,
) -> Saved[ResourceGroup]:
    if group_id is None:
        group = ResourceGroup(organization=organization, **data)
        before: dict[str, Any] = {}
    else:
        found = (
            ResourceGroup.all_objects.select_for_update()
            .filter(organization=organization, pk=group_id)
            .first()
        )
        if found is None:
            raise NotFound("Nie ma takiej grupy.")
        check_version(found.version, expected_version)
        group = found
        before = audit_snapshot(group, _GROUP_FIELDS)
        for name, value in data.items():
            setattr(group, name, value)
    name_taken = ResourceGroup.all_objects.filter(
        organization=organization, name__iexact=group.name
    ).exclude(pk=group.pk)
    if name_taken.exists():
        raise ValidationError({"name": "Grupa o tej nazwie już jest."}, code="name_taken")
    changes = field_changes(before, audit_snapshot(group, _GROUP_FIELDS)) if before else {}
    if changes:
        group.version += 1
    group.save()
    _audit(organization, context, "resource_group", group.id, changes, created=not before)
    return _saved(group, created=not before, changes=changes)
