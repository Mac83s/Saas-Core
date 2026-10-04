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
from datetime import time
from typing import Any, NoReturn
from uuid import UUID

from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.db.models import Count, QuerySet
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import ErrorDetail, NotFound, ParseError, ValidationError

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

from . import cancellation, orders
from . import materials as stock
from .models import (
    PREPAID_POLICIES,
    Appointment,
    AppointmentStatus,
    BookingRule,
    BookingSetupMutation,
    Extra,
    Location,
    PaymentPolicy,
    PriceChange,
    PriceRule,
    PublicBookingRoute,
    RangeUnit,
    Resource,
    ResourceGroup,
    Service,
    ServiceGroup,
    ServiceLocation,
    ServiceResource,
    ServiceStaff,
    StaffChoice,
    StaffMember,
    TimeModel,
)
from .offer_settings import offer_options
from .price_history import record as record_price
from .services import (
    BOOKING_ENABLED,
    BOOKING_MANAGE,
    BookingIdempotencyConflict,
    BookingVersionConflict,
    _assert_appointment_kind_available,
    organization_appointment_kinds,
)
from .unit_content import CONTENT_FIELDS, check_content

#: What the history keeps of a service; the links go in as counts.
_SERVICE_FIELDS = (
    "name",
    "time_model",
    "range_unit",
    "range_start_local",
    "range_end_local",
    "duration_minutes",
    "buffer_before_minutes",
    "buffer_after_minutes",
    "minimum_notice_minutes",
    "booking_window_days",
    "staff_count",
    "public_staff_choice",
    "slot_step_minutes",
    "online",
    "confirmation",
    "response_hours",
    "payment_policy",
    "deposit_percent",
    "transfer_due_days",
    "balance_due_days_before",
    "cancellation_refunds",
    "cancellation_applies_to",
    "active",
)
#: What decides how a customer pays ahead; checked when one of them changes.
_PAYMENT_FIELDS = ("payment_policy", "deposit_percent", "transfer_due_days")
_PLACE_FIELDS = ("name", "address", "active", "online")
_RESOURCE_FIELDS = (
    "name",
    "active",
    "capacity",
    "description",
    "group_id",
    "location_id",
    *CONTENT_FIELDS,
)
_GROUP_FIELDS = ("name", "description", "active")
#: A protective bound, not a business rule: the units one offer's pool is
#: brought up to in one write.
MAX_OFFER_UNITS = 1000
#: How many people one unit may take, as the panel's unit form bounds it.
MAX_UNIT_CAPACITY = 1000
# `slugify` drops what NFKD cannot fold: "Łódź" would become "odz".
_FOLD = str.maketrans({"ł": "l", "Ł": "L"})


@dataclass(frozen=True, slots=True)
class ServiceSetup:
    service: Service
    staff_ids: list[UUID] = field(default_factory=list)
    location_ids: list[UUID] = field(default_factory=list)
    resource_ids: list[UUID] = field(default_factory=list)
    #: The groups of units a `range` offer is booked in (ADR-072 §3).
    group_ids: list[UUID] = field(default_factory=list)
    #: Bookings of it that will still happen; switching it off leaves them (W1).
    future_bookings: int = 0


@dataclass(frozen=True, slots=True)
class Setup:
    services: list[ServiceSetup]
    locations: list[Location]
    resources: list[Resource]
    #: Pools of identical units (ADR-072 §3).
    groups: list[ResourceGroup]
    #: Who can be named as a performer: the company's current people.
    staff: list[StaffMember]
    #: {key: label} of the kinds of visit its services may sell (ADR-050).
    appointment_kinds: dict[str, str] = field(default_factory=dict)


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


@dataclass(frozen=True, slots=True)
class OfferUnits:
    """The pool a stay or a rental is booked in, after `set_offer_units`."""

    service: Service
    group: ResourceGroup
    #: Every switched-on unit of the pool, by name.
    units: list[Resource]
    #: The names of the units this write added.
    added: list[str] = field(default_factory=list)


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
        (ServiceGroup, "groups", "group_id", {}),
    )
    for model, key, column, extra in sources:
        rows = model.all_objects.filter(organization=organization, **extra).order_by("id")
        for service_id, target in rows.values_list("service_id", column):
            links.setdefault(service_id, {}).setdefault(key, []).append(target)
    services = Service.all_objects.filter(organization=organization)
    ahead = dict(
        _future_bookings(organization)
        .values("service_id")
        .annotate(count=Count("id"))
        .values_list("service_id", "count")
    )
    return Setup(
        services=[
            ServiceSetup(
                service,
                links.get(service.id, {}).get("staff", []),
                links.get(service.id, {}).get("locations", []),
                links.get(service.id, {}).get("resources", []),
                links.get(service.id, {}).get("groups", []),
                ahead.get(service.id, 0),
            )
            for service in services
        ],
        locations=list(Location.all_objects.filter(organization=organization)),
        resources=list(Resource.all_objects.filter(organization=organization)),
        groups=list(ResourceGroup.all_objects.filter(organization=organization)),
        staff=list(StaffMember.all_objects.filter(organization=organization, active=True)),
        appointment_kinds=organization_appointment_kinds(organization),
    )


def _future_bookings(organization: Organization) -> QuerySet[Appointment]:
    """Bookings that will still happen: not over and not closed. A status a
    later phase adds (awaiting confirmation, awaiting payment) counts too."""
    return Appointment.all_objects.filter(
        organization=organization, starts_at__gte=timezone.now()
    ).exclude(
        status__in=[
            AppointmentStatus.CANCELED,
            AppointmentStatus.COMPLETED,
            AppointmentStatus.NO_SHOW,
        ]
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
    if created or set(changes) & {"name", "description", "active"}:
        # The catalogue's text, or what it offers, changed (TL12c).
        from .translation_source import notify_catalog_changed

        notify_catalog_changed(context=context)
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
            (ServiceGroup, "group_id", {}),
        )
    }
    return ServiceSetup(
        service,
        links["staff_id"],
        links["location_id"],
        links["resource_id"],
        links["group_id"],
        _future_bookings(organization).filter(service=service).count(),
    )


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


def discard_draft(
    *, service_id: UUID, idempotency_key: str = "", preview: bool = False
) -> Saved[UUID]:
    """Removes an offer that was never switched on and has no bookings, with
    its links, its own seasons, prices, extras and translations — the undo of
    a draft.

    An offer that was ever bookable is not removed: customers, the site and
    the history may name it, so it is switched off instead (`not_a_draft`).
    """
    context, organization = _manage()
    return setup_write(
        context=context,
        action="service.discard",
        target_id=service_id,
        request={},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _discard_draft(context, organization, service_id),
        replay=lambda item_id: Saved(item_id, item_id, 0, False, {}, True),
    )


def _discard_draft(
    context: TenantContext, organization: Organization, service_id: UUID
) -> Saved[UUID]:
    service = (
        Service.all_objects.select_for_update()
        .filter(organization=organization, pk=service_id)
        .first()
    )
    if service is None:
        raise NotFound("Nie ma takiej usługi.")
    if not service.draft:
        _refuse_discard("Tę usługę już włączano: można ją tylko wyłączyć.", "not_a_draft")
    if Appointment.all_objects.filter(organization=organization, service=service).exists():
        _refuse_discard("Usługa ma rezerwacje.", "service_has_bookings")
    # The record of prices keeps what the draft's prices were.
    for price in PriceRule.all_objects.filter(organization=organization, service=service):
        record_price(context, price, PriceChange.DELETED, previous_amount=price.amount_minor)
    # Everything that is the draft's own: its links, seasons, prices and extras.
    for model in (
        ServiceStaff,
        ServiceLocation,
        ServiceResource,
        ServiceGroup,
        BookingRule,
        PriceRule,
        Extra,
    ):
        model.all_objects.filter(organization=organization, service=service).delete()
    # The keys that made or changed it answer with an item that is gone: the
    # same key sent again makes a new draft instead of failing on the old one.
    BookingSetupMutation.all_objects.filter(
        organization=organization, result_kind="service", result_id=service.id
    ).delete()
    _audit(
        organization,
        context,
        "service",
        service.id,
        {"name": {"from": service.name, "to": None}},
        created=False,
    )
    service.delete()
    return Saved(service_id, service_id, 0, False, {"discarded": True})


def _refuse_discard(message: str, code: str) -> NoReturn:
    raise ValidationError({"service_id": [ErrorDetail(message, code=code)]})


#: A stay's default times when the offer names none: check-in 16:00 and
#: check-out 11:00 as in the „Nocleg” preset; pickup 9:00 and return 18:00.
_RANGE_TIMES = {
    RangeUnit.NIGHT: (time(16), time(11)),
    RangeUnit.DAY: (time(9), time(18)),
}


def _check_payment(service: Service, before: dict[str, Any]) -> None:
    """What paying before the booking is confirmed asks of the offer and of
    the company (ADR-072 §8, ADR-073 §5). Asked when the offer's payment
    changes, so an offer set up earlier still saves its other fields."""
    policy = service.payment_policy
    if before and all(before.get(name) == getattr(service, name) for name in _PAYMENT_FIELDS):
        return
    if policy not in PREPAID_POLICIES:
        return
    if not orders.orders_available():
        raise ValidationError({
            "payment_policy": [
                ErrorDetail(
                    "Płatność przed wizytą wymaga zamówień, a plan firmy ich nie obejmuje.",
                    code="orders_required",
                )
            ]
        })
    if policy == PaymentPolicy.TRANSFER and not orders.transfer_account_set():
        raise ValidationError({
            "payment_policy": [
                ErrorDetail(
                    "Najpierw podaj rachunek do przelewów: Ustawienia › Płatności klientów.",
                    code="transfer_account_missing",
                )
            ]
        })


def _check_offer(service: Service, before: dict[str, Any]) -> None:
    """What the offer's time model asks of its other fields (ADR-072 §1–§2)."""
    if (
        before
        and before.get("time_model") != service.time_model
        and (Appointment.all_objects.filter(service=service).exists())
    ):
        raise ValidationError(
            {"time_model": "Usługa z rezerwacjami nie zmienia sposobu rezerwacji."},
            code="time_model_locked",
        )
    if service.time_model == TimeModel.SESSION:
        raise ValidationError(
            {"time_model": "Wydarzenia z miejscami przyjdą później."}, code="time_model_not_ready"
        )
    if service.time_model == TimeModel.SLOT:
        if service.duration_minutes is None:
            raise ValidationError(
                {"duration_minutes": "Podaj czas trwania wizyty."}, code="required"
            )
        if service.staff_count < 1:
            raise ValidationError(
                {"staff_count": "Wizyta potrzebuje co najmniej jednej osoby."}, code="min_value"
            )
        service.range_unit, service.range_start_local, service.range_end_local = "", None, None
        return
    if service.range_unit not in (RangeUnit.NIGHT, RangeUnit.DAY):
        raise ValidationError(
            {"range_unit": "Wybierz, czy liczysz noce, czy dni."},
            code="range_unit_not_ready" if service.range_unit == RangeUnit.HOUR else "required",
        )
    service.duration_minutes = None
    default_start, default_end = _RANGE_TIMES[RangeUnit(service.range_unit)]
    service.range_start_local = service.range_start_local or default_start
    service.range_end_local = service.range_end_local or default_end
    if service.range_unit == RangeUnit.DAY and service.range_end_local <= service.range_start_local:
        raise ValidationError(
            {"range_end_local": "Zwrot musi być po odbiorze tego samego dnia."},
            code="end_before_start",
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
    group_ids = values.pop("group_ids", None)
    materials = values.pop("materials", None)
    if "cancellation_refunds" in values:
        values["cancellation_refunds"] = cancellation.normalized(values["cancellation_refunds"])
    if service_id is None:
        _assert_appointment_kind_available(organization, values.get("appointment_kind", ""))
        service = Service(
            organization=organization,
            public_slug=_free_slug(Service, organization, values.get("name", "")),
            # The conversation, when the assistant made it (ADR-072 §11).
            origin_ref=context.acting_ref if context.acting_via == "assistant" else "",
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
    _check_payment(service, before)
    _check_offer(service, before)
    # Made switched off, it is a draft until somebody switches it on.
    service.draft = not service.active and (service.draft or not before)
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
        ("groups", "group_ids", ResourceGroup, ServiceGroup, "group_id", {}, group_ids),
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
    found = None
    if resource_id is not None:
        found = (
            Resource.all_objects.select_for_update()
            .filter(organization=organization, pk=resource_id)
            .first()
        )
        if found is None:
            raise NotFound("Nie ma takiego zasobu.")
        check_version(found.version, expected_version)
    data = dict(data)
    check_content(organization, found, data)
    _unit_address(organization, found, data)
    if found is None:
        resource = Resource(organization=organization, **data)
        before: dict[str, Any] = {}
    else:
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


def _unit_address(organization: Organization, unit: Resource | None, data: dict[str, Any]) -> None:
    """A unit's address segment (ADR-072, slice 5c): what the company typed,
    as a slug that no other unit of the company has (400 `slug_taken`); a unit
    shown to guests without one gets it from its name."""
    address = unit.public_slug if unit is not None else ""
    if "public_slug" in data:
        address = slugify(str(data["public_slug"] or "").translate(_FOLD))[:80]
        others = Resource.all_objects.filter(organization=organization, public_slug=address)
        if unit is not None:
            others = others.exclude(pk=unit.pk)
        if address and others.exists():
            raise ValidationError({
                "public_slug": [ErrorDetail("Ten adres ma już inna jednostka.", code="slug_taken")]
            })
        data["public_slug"] = address
    shown = data.get("public", unit.public if unit is not None else False)
    if shown and not address:
        name = data.get("name", unit.name if unit is not None else "")
        data["public_slug"] = _free_slug(Resource, organization, str(name))


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


@transaction.atomic
def set_offer_units(
    *,
    service_id: UUID,
    count: int,
    capacity: int | None = None,
    location_id: UUID | None = None,
    idempotency_key: str = "",
    expected_version: int | None = None,
    preview: bool = False,
) -> Saved[OfferUnits]:
    """Brings a stay's or a rental's pool up to `count` identical units, in
    one write: the offer's group — made under the offer's name when it has
    none, or the company's group of that name — linked to the offer, and the
    units it lacks, named after the group („Domki 1”, „Domki 2”).

    It only ever adds. Fewer than the pool has is refused
    (`units_cannot_be_removed`): a unit may hold bookings, so one is switched
    off by name, never by a count. `capacity` and `location_id` describe the
    units added; the ones already there stay as they are.
    """
    context, organization = _manage()
    return setup_write(
        context=context,
        action="service.units",
        target_id=service_id,
        request={
            "count": count,
            "capacity": capacity,
            "location_id": location_id,
            "expected_version": expected_version,
        },
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _write_offer_units(
            context, organization, service_id, count, capacity, location_id, expected_version
        ),
        replay=lambda item_id: _replayed_units(organization, item_id),
    )


def _pool(group: ResourceGroup) -> list[Resource]:
    return list(Resource.all_objects.filter(group=group, active=True).order_by("name", "id"))


def _replayed_units(organization: Organization, service_id: UUID) -> Saved[OfferUnits]:
    service = Service.all_objects.filter(organization=organization, pk=service_id).first()
    link = (
        ServiceGroup.all_objects.filter(organization=organization, service_id=service_id)
        .select_related("group")
        .order_by("id")
        .first()
    )
    if service is None or link is None:
        # The key's first answer was about an offer discarded since.
        raise NotFound("Tej usługi albo jej jednostek już nie ma.")
    return Saved(
        OfferUnits(service, link.group, _pool(link.group)),
        service.id,
        service.version,
        False,
        {},
        True,
    )


def _refuse_units(field_name: str, message: str, code: str) -> NoReturn:
    raise ValidationError({field_name: [ErrorDetail(message, code=code)]})


def _write_offer_units(
    context: TenantContext,
    organization: Organization,
    service_id: UUID,
    count: int,
    capacity: int | None,
    location_id: UUID | None,
    expected_version: int | None,
) -> Saved[OfferUnits]:
    service = (
        Service.all_objects.select_for_update()
        .filter(organization=organization, pk=service_id)
        .first()
    )
    if service is None:
        raise NotFound("Nie ma takiej usługi.")
    check_version(service.version, expected_version)
    if service.time_model != TimeModel.RANGE:
        _refuse_units(
            "service_id",
            "Jednostki ma usługa rezerwowana na noce albo dni.",
            "units_need_range_offer",
        )
    if not 1 <= count <= MAX_OFFER_UNITS:
        _refuse_units("count", f"Podaj liczbę od 1 do {MAX_OFFER_UNITS}.", "out_of_range")
    if capacity is not None and not 1 <= capacity <= MAX_UNIT_CAPACITY:
        # The panel's own bound for a unit (`ResourceInputSerializer`).
        _refuse_units("capacity", f"Podaj liczbę osób od 1 do {MAX_UNIT_CAPACITY}.", "out_of_range")
    if location_id is not None:
        _own(Location, organization, [location_id], "location_id")
    linked = list(
        ServiceGroup.all_objects.filter(organization=organization, service=service)
        .order_by("id")
        .values_list("group_id", flat=True)
    )
    if len(linked) > 1:
        _refuse_units(
            "service_id",
            "Ta usługa ma kilka grup jednostek — jednostki dodasz w panelu, we właściwej grupie.",
            "several_unit_groups",
        )
    changes: dict[str, Any] = {}
    if linked:
        group = ResourceGroup.all_objects.select_for_update().get(pk=linked[0])
    else:
        # The company's group of the offer's name is the offer's pool: made
        # again after a discarded draft, the offer finds its units.
        found = (
            ResourceGroup.all_objects.select_for_update()
            .filter(organization=organization, name__iexact=service.name)
            .first()
        )
        group = (
            found
            if found is not None
            else _write_group(context, organization, None, {"name": service.name}, None).value
        )
        _relink(ServiceGroup, organization, service, "group_id", [group.id])
        changes["groups"] = {"changed": True}
    if not group.active:
        # A switched-off pool gives no unit to anybody: adding to it would
        # look done and book nothing.
        _refuse_units(
            "service_id",
            f"Grupa jednostek „{group.name}” jest wyłączona — włącz ją w panelu.",
            "unit_group_switched_off",
        )
    units = _pool(group)
    if count < len(units):
        _refuse_units(
            "count",
            f"Grupa „{group.name}” ma już {len(units)} jedn. Jednostek nie usuwam: "
            "zbędną wyłączysz w panelu.",
            "units_cannot_be_removed",
        )
    taken = {
        name.casefold()
        for name in Resource.all_objects.filter(group=group).values_list("name", flat=True)
    }
    added: list[str] = []
    number = 0
    while len(units) + len(added) < count:
        number += 1
        name = f"{group.name[:150]} {number}"
        if name.casefold() in taken:
            continue
        _write_resource(
            context,
            organization,
            None,
            {"name": name, "group_id": group.id, "capacity": capacity, "location_id": location_id},
            None,
        )
        added.append(name)
    if added:
        changes["units"] = {"from": len(units), "to": count}
    if changes:
        service.version += 1
        service.save(update_fields=["version", "updated_at"])
    _audit(organization, context, "service", service.id, changes, created=False)
    return Saved(
        OfferUnits(service, group, _pool(group), added),
        service.id,
        service.version,
        False,
        changes,
    )
