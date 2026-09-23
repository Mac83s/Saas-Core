"""Use cases of the farm register (ADR-051).

Every one goes through `authorize_entitled`: the permission says the person may
do it, the entitlement says the organization's plan includes the register.
Reads and writes happen under the tenant, so another organization's farm is
simply not found — the database guard is the second line, not the first.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any, cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpRequest
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import (
    audit_snapshot,
    field_changes,
    record_audit,
)
from saas_core.modules.core.organizations.models import Organization, OrganizationAuditAction
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .models import Animal, AnimalHealthEntry, Farm, HealthEntryKind
from .species import (
    HERD_NUMBER,
    SPECIES,
    TAX_ID,
    normalize_herd_number,
    normalize_identifier,
)

FARMS_READ = "farms.read"
FARMS_MANAGE = "farms.manage"
FARMS_ENABLED = "farms.enabled"

#: A working list; nobody scrolls past a few hundred rows without searching.
PAGE_LIMIT = 500

#: Written here by a person, not published by a vertical.
MANUAL_SOURCE = "farms.manual"

#: The unique constraints a person can hit, and what to tell them. The database
#: decides, so two people saving the same farm at once get the same answer as
#: one person saving it twice.
DUPLICATES = {
    "farms_farm_org_name_uq": ("name", "Gospodarstwo o tej nazwie już jest."),
    "farms_farm_org_herd_number_uq": (
        "herd_number",
        "Gospodarstwo z tym numerem siedziby stada już jest.",
    ),
    "farms_animal_farm_tag_uq": ("national_id", "To zwierzę jest już w tym gospodarstwie."),
}


def _unique[T](write: Callable[[], T]) -> T:
    try:
        with transaction.atomic():
            return write()
    except IntegrityError as error:
        diag = getattr(error.__cause__, "diag", None)
        duplicate = DUPLICATES.get(getattr(diag, "constraint_name", None) or "")
        if duplicate is None:
            raise
        field, message = duplicate
        raise ValidationError({field: message}) from error


def _clean_farm(data: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(data)
    if "herd_number" in cleaned:
        cleaned["herd_number"] = normalize_herd_number(cleaned["herd_number"] or "")
        if cleaned["herd_number"] and not HERD_NUMBER.fullmatch(cleaned["herd_number"]):
            raise ValidationError({
                "herd_number": "Numer siedziby stada ma postać np. PL012345678-001."
            })
    if "tax_id" in cleaned:
        raw = (cleaned["tax_id"] or "").strip()
        cleaned["tax_id"] = "".join(ch for ch in raw if ch.isdigit())
        # Only an empty field clears the NIP; "brak" is a typo, not a request.
        if raw and not TAX_ID.fullmatch(cleaned["tax_id"]):
            raise ValidationError({"tax_id": "NIP ma 10 cyfr."})
    return cleaned


def _mirror(request: HttpRequest, animal: Animal) -> None:
    """A shared card writes the cow into the farmer's register too (ADR-051 pt 7).

    Imported here rather than at module level: the door lives one layer above
    this one, in a module that reads these use cases.
    """
    from .herd_sync import mirror_animal  # noqa: PLC0415

    mirror_animal(request, animal)


def _clean_animal(data: dict[str, Any], *, species: str) -> dict[str, Any]:
    cleaned = dict(data)
    known = SPECIES.get(species)
    if known is None or not known.active:
        raise ValidationError({"species": "Ten gatunek nie jest jeszcze obsługiwany."})
    if "national_id" in cleaned:
        cleaned["national_id"] = normalize_identifier(cleaned["national_id"])
        if not known.identifier.fullmatch(cleaned["national_id"]):
            raise ValidationError({
                "national_id": "Numer nie ma formatu numeru identyfikacyjnego tego gatunku."
            })
    return cleaned


#: The keeper's own data: the history says it changed, never what it was.
FARM_PRIVATE = ("tax_id", "address", "keeper_name", "email", "phone", "notes")


def audit_farm(
    request: HttpRequest,
    organization_id: UUID,
    action: str,
    target: Farm | Animal,
    metadata: dict[str, Any] | None = None,
) -> None:
    record_audit(
        organization=Organization.objects.get(pk=organization_id),
        action=action,
        actor=cast(User, request.user),
        target_type=target._meta.model_name or "",
        target_id=target.id,
        metadata=metadata,
    )


def list_farms(*, search: str = "") -> list[Farm]:
    context = authorize_entitled(FARMS_READ, FARMS_ENABLED, operation=FeatureOperation.READ)
    query = Farm.all_objects.filter(organization_id=context.organization_id)
    if search:
        query = query.filter(
            Q(name__icontains=search)
            | Q(village__icontains=search)
            | Q(keeper_name__icontains=search)
            | Q(herd_number__icontains=normalize_identifier(search))
        )
    return list(query.annotate(animal_count=Count("animals"))[:PAGE_LIMIT])


def get_farm(farm_id: UUID) -> Farm:
    context = authorize_entitled(FARMS_READ, FARMS_ENABLED, operation=FeatureOperation.READ)
    farm = (
        Farm.all_objects.filter(organization_id=context.organization_id, id=farm_id)
        .annotate(animal_count=Count("animals"))
        .first()
    )
    if farm is None:
        raise NotFound("Nie ma takiego gospodarstwa.")
    return farm


@transaction.atomic
def create_farm(*, request: HttpRequest, data: dict[str, Any]) -> Farm:
    context = authorize_entitled(FARMS_MANAGE, FARMS_ENABLED)
    cleaned = _clean_farm(data)
    farm = _unique(
        lambda: Farm.all_objects.create(organization_id=context.organization_id, **cleaned)
    )
    # The reads annotate `animal_count`; a written farm answers with it too.
    setattr(farm, "animal_count", 0)  # noqa: B010
    audit_farm(request, context.organization_id, OrganizationAuditAction.FARM_CREATED, farm)
    return farm


@transaction.atomic
def update_farm(*, request: HttpRequest, farm_id: UUID, data: dict[str, Any]) -> Farm:
    context = authorize_entitled(FARMS_MANAGE, FARMS_ENABLED)
    farm = (
        Farm.all_objects.select_for_update()
        .filter(organization_id=context.organization_id, id=farm_id)
        .first()
    )
    if farm is None:
        raise NotFound("Nie ma takiego gospodarstwa.")
    cleaned = _clean_farm(data)
    before = audit_snapshot(farm, cleaned)
    for field, value in cleaned.items():
        setattr(farm, field, value)
    _unique(farm.save)
    setattr(farm, "animal_count", Animal.all_objects.filter(farm=farm).count())  # noqa: B010
    audit_farm(
        request,
        context.organization_id,
        OrganizationAuditAction.FARM_UPDATED,
        farm,
        {"changes": field_changes(before, audit_snapshot(farm, cleaned), private=FARM_PRIVATE)},
    )
    return farm


def list_animals(
    *, farm_id: UUID | None = None, search: str = "", review: bool = False
) -> list[Animal]:
    context = authorize_entitled(FARMS_READ, FARMS_ENABLED, operation=FeatureOperation.READ)
    query = Animal.all_objects.filter(organization_id=context.organization_id)
    if farm_id is not None:
        query = query.filter(farm_id=farm_id)
    if review:
        query = query.filter(review_requested_at__isnull=False)
    if search:
        needle = normalize_identifier(search)
        query = query.filter(
            Q(national_id__icontains=needle)
            | Q(working_number__iexact=search.strip())
            | Q(name__icontains=search.strip())
        )
    return list(query.select_related("farm")[:PAGE_LIMIT])


def list_health_entries(
    *,
    animal_id: UUID,
    kinds: Sequence[str] = (),
    author: str = "",
    since: date | None = None,
    until: date | None = None,
) -> list[AnimalHealthEntry]:
    """An animal's history, newest first, filtered the way the panel asks.

    The filters run in the database on purpose: the list is cut at `PAGE_LIMIT`,
    so filtering after that would quietly hide the older entries the feed exists
    to show.
    """
    context = authorize_entitled(FARMS_READ, FARMS_ENABLED, operation=FeatureOperation.READ)
    query = AnimalHealthEntry.all_objects.filter(
        organization_id=context.organization_id, animal_id=animal_id
    )
    if kinds:
        query = query.filter(kind__in=kinds)
    if author == "mine":
        query = query.filter(author_organization_id=context.organization_id)
    elif author == "others":
        query = query.exclude(author_organization_id=context.organization_id)
    if since is not None:
        query = query.filter(occurred_on__gte=since)
    if until is not None:
        query = query.filter(occurred_on__lte=until)
    entries = list(query[:PAGE_LIMIT])
    for entry in entries:
        entry.author_is_external = entry.author_organization_id not in (
            None,
            context.organization_id,
        )
    # A company working on a shared card reads the animal's file in the
    # farmer's register too (ADR-051 pt 8). Imported here, like `_mirror`: the
    # door lives one layer above these use cases.
    from .herd_sync import registry_health_entries  # noqa: PLC0415

    entries.extend(
        entry
        for entry in registry_health_entries(animal_id)
        if _matches(entry, kinds=kinds, author=author, since=since, until=until, context=context)
    )
    entries.sort(key=lambda entry: (entry.occurred_on, entry.published_at), reverse=True)
    return entries[:PAGE_LIMIT]


def _matches(
    entry: AnimalHealthEntry,
    *,
    kinds: Sequence[str],
    author: str,
    since: date | None,
    until: date | None,
    context: Any,
) -> bool:
    """The register's rows come back through the door, so the filters that ran
    in the database have to run on them too."""
    if kinds and entry.kind not in kinds:
        return False
    if author == "mine" and entry.author_organization_id != context.organization_id:
        return False
    if author == "others" and entry.author_organization_id == context.organization_id:
        return False
    if since is not None and entry.occurred_on < since:
        return False
    return not (until is not None and entry.occurred_on > until)


@transaction.atomic
def record_health_entry(
    *, request: HttpRequest, animal_id: UUID, data: dict[str, Any]
) -> AnimalHealthEntry:
    """An entry written here, by hand: a note, a warning, a medicine given.

    `source` is the server's, never the client's: it is half of the key a
    vertical publishes by, and a client that could name it would overwrite
    somebody else's entry through the same `update_or_create`.
    """
    context = authorize_entitled(FARMS_MANAGE, FARMS_ENABLED)
    animal = Animal.all_objects.filter(
        organization_id=context.organization_id, id=animal_id
    ).first()
    if animal is None:
        raise NotFound("Nie ma takiego zwierzęcia.")
    user = cast(User, request.user)
    entry = AnimalHealthEntry.all_objects.create(
        organization_id=context.organization_id,
        animal=animal,
        kind=data.get("kind") or HealthEntryKind.NOTE,
        occurred_on=data.get("occurred_on") or timezone.localdate(),
        source=MANUAL_SOURCE,
        source_reference=str(uuid.uuid7()),
        author_name=f"{user.first_name} {user.last_name}".strip() or user.email,
        author_organization_id=context.organization_id,
        author_organization_name=_organization_name(context.organization_id),
        summary=data["summary"].strip(),
        details=data.get("details") or {},
        private=bool(data.get("private")),
        photos=[str(photo) for photo in data.get("photos") or []],
    )
    entry.author_is_external = False
    audit_farm(
        request, context.organization_id, OrganizationAuditAction.ANIMAL_HEALTH_RECORDED, animal
    )
    return entry


def _organization_name(organization_id: UUID) -> str:
    """The caller's own organization — the only one its tenant may read."""
    return (
        Organization.objects.filter(id=organization_id).values_list("name", flat=True).first() or ""
    )


@transaction.atomic
def create_animal(*, request: HttpRequest, farm_id: UUID, data: dict[str, Any]) -> Animal:
    context = authorize_entitled(FARMS_MANAGE, FARMS_ENABLED)
    farm = Farm.all_objects.filter(organization_id=context.organization_id, id=farm_id).first()
    if farm is None:
        raise NotFound("Nie ma takiego gospodarstwa.")
    species = data.pop("species", "cattle")
    cleaned = _clean_animal(data, species=species)
    animal = _unique(
        lambda: Animal.all_objects.create(
            organization_id=context.organization_id, farm=farm, species=species, **cleaned
        )
    )
    audit_farm(request, context.organization_id, OrganizationAuditAction.ANIMAL_CREATED, animal)
    _mirror(request, animal)
    return animal


@transaction.atomic
def update_animal(*, request: HttpRequest, animal_id: UUID, data: dict[str, Any]) -> Animal:
    context = authorize_entitled(FARMS_MANAGE, FARMS_ENABLED)
    animal = (
        Animal.all_objects.select_for_update()
        .filter(organization_id=context.organization_id, id=animal_id)
        .first()
    )
    if animal is None:
        raise NotFound("Nie ma takiego zwierzęcia.")
    reviewed = data.pop("reviewed", None)
    cleaned = _clean_animal(data, species=animal.species)
    before = audit_snapshot(animal, cleaned)
    for field, value in cleaned.items():
        setattr(animal, field, value)
    if reviewed:
        # Przejrzane przez hodowcę: znacznik znika, wiersz zostaje.
        animal.review_requested_at = None
    _unique(animal.save)
    audit_farm(
        request,
        context.organization_id,
        OrganizationAuditAction.ANIMAL_UPDATED,
        animal,
        {"changes": field_changes(before, audit_snapshot(animal, cleaned))},
    )
    _mirror(request, animal)
    return animal
