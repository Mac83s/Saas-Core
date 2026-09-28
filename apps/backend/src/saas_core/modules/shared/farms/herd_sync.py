"""What a company writes into the farmer's register (ADR-051 pt 7).

The company records a cow on its card; the farmer's register is the source of
truth for the herd, so the same cow has to land there too. Both organizations
are tenants with row-level security, and the company cannot see, let alone
write, the farmer's rows — so the write happens through a door that is opened
on purpose and closed right after: `registry_writer` activates the registry's
tenant context for exactly the statements inside it.

What makes this a door rather than a hole:

- it opens only for an active `FarmShare` with `can_write_herd`, which the
  farmer granted and can revoke;
- it carries one permission (`farms.manage`) and one organization, and the
  actor stays the person from the company, so the farmer's audit log says who
  wrote;
- `SET LOCAL` lives until the end of the transaction, not the end of a block,
  so leaving restores the caller's organization — otherwise the rest of the
  company's transaction would quietly run as the farmer.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import date, datetime
from typing import Any
from uuid import UUID

from django.core.serializers.json import DjangoJSONEncoder
from django.db import DatabaseError, transaction
from django.db.models import Max, Q
from django.http import HttpRequest
from django.utils import timezone
from rest_framework.exceptions import NotFound

from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    require_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    MembershipStatus,
    OrganizationAuditAction,
)
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled
from saas_core.modules.shared.media.api import MEDIA_READ, read_media_preview
from saas_core.modules.shared.notifications.api import notify_in_app

from .models import (
    Animal,
    AnimalHealthEntry,
    AnimalStatus,
    Farm,
    FarmShare,
    FarmVisitEntry,
    HealthEntryKind,
    ShareStatus,
    VisitStatus,
)
from .services import FARMS_ENABLED, FARMS_MANAGE, FARMS_READ, PAGE_LIMIT, audit_farm
from .sharing import (
    Conflict,
    share_for_publishing,
    share_for_schedule,
    share_for_writing,
)

#: What the register receives about an animal. The company's private note about
#: a cow stays with the company, like the private note on a card.
SYNCED_FIELDS = (
    "working_number",
    "name",
    "sex",
    "birth_date",
    "status",
)


@contextmanager
def registry_door(share: FarmShare, *, permission: str = FARMS_MANAGE) -> Iterator[TenantContext]:
    """The farmer's tenant, for the statements the share allows.

    Reading takes `farms.read`, writing `farms.manage`: nothing inside calls
    `authorize*` today, but a context that carries more than it needs is a
    permission waiting to be used by accident.
    """
    caller = require_tenant_context()
    context = TenantContext(
        organization_id=share.registry_organization_id,
        membership_id=caller.membership_id,
        actor_id=caller.actor_id,
        role_key="farm_share",
        permissions=frozenset({permission}),
        principal_kind="farm_share",
    )
    with activate_tenant_context(context):
        set_local_organization_id(context.organization_id)
        try:
            yield context
        finally:
            # A failed statement leaves the transaction aborted and this would
            # raise over the real error; the savepoint of the caller's
            # `atomic()` restores the setting anyway.
            with suppress(DatabaseError):
                set_local_organization_id(caller.organization_id)


def mirror_animal(request: HttpRequest, animal: Animal) -> Animal | None:
    """The same cow in the farmer's register, when the card is shared.

    Returns the registry's animal, or None when this farm is nobody's: most
    cards are not linked, and an unlinked card is the ordinary case, not an
    error.
    """
    share = share_for_writing(animal.organization_id, animal.farm_id)
    if share is None:
        return None
    values = _values(animal)
    with transaction.atomic(), registry_door(share) as context:
        farm = Farm.all_objects.filter(
            organization_id=context.organization_id, id=share.registry_farm_id
        ).first()
        if farm is None:
            # The farmer deleted the farm the share points at; the share is
            # stale and the company's own record already stands.
            return None
        existing = _registry_animal(context, share, animal)
        if _diverges(existing, values):
            # The keeper decides what to do with it; nothing here is deleted or
            # asked about, it is only marked as worth a look (ADR-051 pt 7).
            values["review_requested_at"] = timezone.now()
        mirrored, created = Animal.all_objects.update_or_create(
            organization_id=context.organization_id,
            farm=farm,
            species=animal.species,
            national_id=animal.national_id,
            defaults=values,
        )
        audit_farm(
            request,
            context.organization_id,
            OrganizationAuditAction.ANIMAL_CREATED
            if created
            else OrganizationAuditAction.ANIMAL_UPDATED,
            mirrored,
        )
        return mirrored


@transaction.atomic
def push_herd(request: HttpRequest, *, farm_id: UUID) -> dict[str, int]:
    """The company's whole card, written into the farmer's register at once.

    This is what closes the window the activation code leaves open: the card is
    copied when the code is issued, so a cow recorded between issuing it and
    redeeming it never reaches the register. One door for the whole herd rather
    than one per animal — a herd of three hundred would otherwise be three
    hundred context switches and three hundred audit entries.

    Only animals still in the herd travel: the card also keeps the sold and the
    dead, and a register that never knew them does not need their history.
    """
    context = authorize_entitled(FARMS_MANAGE, FARMS_ENABLED)
    if not Farm.all_objects.filter(organization_id=context.organization_id, id=farm_id).exists():
        raise NotFound("Nie ma takiego gospodarstwa.")
    share = share_for_writing(context.organization_id, farm_id)
    if share is None:
        raise Conflict("To gospodarstwo nie jest połączone z kontem rolnika.")
    # Locked for the duration: two clicks would otherwise insert the same
    # missing animals twice and the second would hit the unique tag.
    FarmShare.objects.select_for_update().filter(pk=share.pk).first()
    # Read the company's herd before the door opens: inside it, these rows are
    # invisible (the whole reason the handover travels in the code).
    ours = {
        _tag(animal): _values(animal)
        for animal in Animal.all_objects.filter(
            organization_id=context.organization_id,
            farm_id=farm_id,
            status=AnimalStatus.ACTIVE,
        )
    }
    now = timezone.now()
    with registry_door(share) as registry:
        farm = Farm.all_objects.filter(
            organization_id=registry.organization_id, id=share.registry_farm_id
        ).first()
        if farm is None:
            raise Conflict("Gospodarstwo w rejestrze rolnika już nie istnieje.")
        theirs = {
            _tag(animal): animal
            for animal in Animal.all_objects.filter(
                organization_id=registry.organization_id, farm_id=farm.id
            )
        }
        missing: list[Animal] = []
        changed: list[Animal] = []
        for tag, values in ours.items():
            existing = theirs.get(tag)
            if existing is None:
                missing.append(
                    Animal(
                        organization_id=registry.organization_id,
                        farm=farm,
                        species=tag[0],
                        national_id=tag[1],
                        review_requested_at=now,
                        **values,
                    )
                )
            elif _diverges(existing, values):
                for field, value in values.items():
                    setattr(existing, field, value)
                existing.review_requested_at = now
                # `bulk_update` skips `save()`, so `auto_now` would not fire and
                # the keeper's list would show a stale "last changed".
                existing.updated_at = now
                changed.append(existing)
        Animal.all_objects.bulk_create(missing, batch_size=100)
        if changed:
            Animal.all_objects.bulk_update(
                changed,
                [*SYNCED_FIELDS, "review_requested_at", "updated_at"],
                batch_size=100,
            )
        result = {
            "added": len(missing),
            "updated": len(changed),
            "unchanged": len(ours) - len(missing) - len(changed),
        }
        # One entry for the whole herd: three hundred lines would say less.
        audit_farm(
            request,
            registry.organization_id,
            OrganizationAuditAction.HERD_PUSHED,
            farm,
            metadata=result,
        )
    return result


def _tag(animal: Animal) -> tuple[str, str]:
    """The one rule that matches an animal across two registers."""
    return (animal.species, animal.national_id)


def _values(animal: Animal) -> dict[str, Any]:
    return {field: getattr(animal, field) for field in SYNCED_FIELDS}


def _diverges(existing: Animal | None, values: dict[str, Any]) -> bool:
    """Whether this write tells the keeper something they do not have.

    A new animal does; an unchanged one does not — a visit writing the same
    forty cows every month would otherwise be forty things to review.
    """
    if existing is None:
        return True
    return any(getattr(existing, field) != value for field, value in values.items())


#: What makes two revisions the same entry. A correction that says nothing new
#: writes nothing: a card saved twice, or a retry, leaves one revision.
_CONTENT = (
    "kind",
    "occurred_on",
    "author_name",
    "author_organization_id",
    "author_organization_name",
    "summary",
    "details",
    "photos",
    "withdrawal_milk_until",
    "withdrawal_meat_until",
)

#: The keeper's inbox learns about a correction of what a company published.
CORRECTION_NOTIFICATION = "farms.health_corrected"


def _same(entry: AnimalHealthEntry, values: dict[str, Any]) -> bool:
    """Field by field: dates and moments compare as values (a moment in Warsaw
    time is the same moment in UTC), JSON as the database hands it back."""
    for field in _CONTENT:
        ours, theirs = getattr(entry, field), values[field]
        if field in ("details", "photos"):
            theirs = json.loads(json.dumps(theirs, cls=DjangoJSONEncoder))
        if ours != theirs:
            return False
    return True


def _write_revision(
    *,
    organization_id: UUID,
    animal: Animal,
    source: str,
    reference: str,
    values: dict[str, Any],
    correction: str | None,
    corrected_by: str,
    require_current: bool,
) -> tuple[AnimalHealthEntry | None, bool]:
    """The entry in force for (source, reference), and whether this wrote it.

    An entry is never rewritten nor deleted (decision of 28.09). Without a
    correction an existing entry stays as it is — a replay, or a second close
    of a visit, cannot change what the reader already has. With one, a
    different content becomes the next revision pointing at the entry it
    replaces, and that one is marked retracted, not removed. `correction` is the
    reason; None means "not a correction", and an empty reason is still one — a
    keeper's private note is corrected without explaining it to anybody.
    """
    lineage = AnimalHealthEntry.all_objects.filter(
        organization_id=organization_id, animal=animal, source=source, source_reference=reference
    )
    current = lineage.filter(retracted_at__isnull=True).select_for_update().first()
    if current is None and require_current:
        return None, False
    if current is not None and (correction is None or _same(current, values)):
        return current, False
    latest = lineage.aggregate(latest=Max("revision"))["latest"]
    if current is not None:
        lineage.filter(pk=current.pk).update(retracted_at=timezone.now())
    entry = AnimalHealthEntry.all_objects.create(
        organization_id=organization_id,
        animal=animal,
        source=source,
        source_reference=reference,
        revision=0 if latest is None else latest + 1,
        corrects=current,
        correction_reason=correction or "",
        corrected_by=corrected_by if correction is not None else "",
        **values,
    )
    return entry, True


def publish_health_entry(
    *,
    animal: Animal,
    occurred_on: date,
    source: str,
    reference: str,
    summary: str,
    kind: str = HealthEntryKind.TREATMENT,
    author_name: str = "",
    details: dict[str, Any] | None = None,
    photos: list[str] | None = None,
    withdrawal_milk_until: datetime | None = None,
    withdrawal_meat_until: datetime | None = None,
    correction: str = "",
    corrected_by: str = "",
    require_current: bool = False,
) -> AnimalHealthEntry | None:
    """One entry in the farmer's register about an animal (ADR-051 pt 8).

    Called by a vertical while the company's context is active; the animal is
    the company's own, and its counterpart in the register is found by tag.
    The entry names its author and its day, so it is its own audit trail.

    Publishing again changes nothing the keeper already has. A `correction`
    (the reason, as the keeper reads it) publishes the next revision instead
    and tells the keeper's people; `require_current` corrects only what the
    register holds — a withdrawal of something never published says nothing.
    """
    share = share_for_publishing(animal.organization_id, animal.farm_id)
    if share is None:
        return None
    with transaction.atomic(), registry_door(share) as context:
        mirrored = _registry_animal(context, share, animal)
        if mirrored is None:
            # The register does not know this cow; the herd write is what puts
            # it there, and without it there is nothing to hang a history on.
            return None
        entry, written = _write_revision(
            organization_id=context.organization_id,
            animal=mirrored,
            source=source,
            reference=reference,
            values={
                "kind": kind,
                "occurred_on": occurred_on,
                "author_name": author_name or share.company_name,
                "author_organization_id": share.company_organization_id,
                "author_organization_name": share.company_name,
                "summary": summary,
                "details": details or {},
                "photos": list(photos or []),
                "withdrawal_milk_until": withdrawal_milk_until,
                "withdrawal_meat_until": withdrawal_meat_until,
            },
            correction=correction or None,
            corrected_by=corrected_by,
            require_current=require_current,
        )
        if written and correction:
            _tell_the_keeper(context.organization_id, share, mirrored, correction)
        return entry


def _tell_the_keeper(
    organization_id: UUID, share: FarmShare, animal: Animal, correction: str
) -> None:
    """One message per farm, day and reason: a visit corrected on ten cows is
    one thing to read, not ten (decision 2A of 28.09)."""
    digest = hashlib.sha256(correction.encode()).hexdigest()[:12]
    key = f"farms-health-corrected:{animal.farm_id}:{timezone.localdate().isoformat()}:{digest}"
    payload = {
        "farm_id": str(animal.farm_id),
        "farm_name": animal.farm.name,
        "company_name": share.company_name,
        "national_id": animal.national_id,
        "reason": correction,
    }
    for membership in Membership.objects.select_related("role").filter(
        organization_id=organization_id, status=MembershipStatus.ACTIVE
    ):
        if FARMS_MANAGE in (membership.role.permissions or []):
            notify_in_app(
                organization_id=organization_id,
                user_id=membership.user_id,
                kind=CORRECTION_NOTIFICATION,
                payload=payload,
                idempotency_key=key,
            )


def record_own_health_entry(
    *,
    animal: Animal,
    occurred_on: date,
    source: str,
    reference: str,
    summary: str,
    kind: str = HealthEntryKind.TREATMENT,
    author_name: str = "",
    details: dict[str, Any] | None = None,
    withdrawal_milk_until: datetime | None = None,
    withdrawal_meat_until: datetime | None = None,
    correction: str = "",
    corrected_by: str = "",
) -> AnimalHealthEntry | None:
    """The same kind of entry on the company's own card of the animal.

    What a company did to an animal belongs on its own card too, shared farm
    or not — a medicine and its withdrawal most of all. Same key and the same
    rule as publishing: writing again changes nothing, a correction writes the
    next revision. On a shared card the register's copy of a revision is not
    shown a second time (`list_health_entries`).
    """
    from saas_core.modules.core.organizations.models import Organization  # noqa: PLC0415

    organization = Organization.objects.get(pk=animal.organization_id)
    entry, _ = _write_revision(
        organization_id=animal.organization_id,
        animal=animal,
        source=source,
        reference=reference,
        values={
            "kind": kind,
            "occurred_on": occurred_on,
            "author_name": author_name or organization.name,
            "author_organization_id": animal.organization_id,
            "author_organization_name": organization.name,
            "summary": summary,
            "details": details or {},
            "photos": [],
            "withdrawal_milk_until": withdrawal_milk_until,
            "withdrawal_meat_until": withdrawal_meat_until,
        },
        correction=correction or None,
        corrected_by=corrected_by,
        require_current=False,
    )
    return entry


def retract_own_health_entry(*, animal: Animal, source: str, reference: str) -> None:
    """An entry the company took back (an undone record) stays on its own card,
    marked retracted: it no longer counts, a withdrawal period included."""
    AnimalHealthEntry.all_objects.filter(
        organization_id=animal.organization_id,
        animal=animal,
        source=source,
        source_reference=reference,
        retracted_at__isnull=True,
    ).update(retracted_at=timezone.now())


def read_entry_photo(*, entry_id: UUID, media_id: UUID) -> bytes:
    """Zdjęcie dołączone do wpisu kartoteki — z magazynu jego autora.

    Plik nie jest kopiowany do rejestru: zostaje tam, gdzie go zrobiono, a
    czytelnik wchodzi przez ten wpis (decyzja z 20.09). Bramką jest to, że
    zdjęcie stoi na wpisie, który czytelnik ma u siebie, i że udział z autorem
    nadal żyje — cofnięty udział zamyka też zdjęcia, bez sprzątania plików.
    """
    context = authorize_entitled(FARMS_READ, FARMS_ENABLED, operation=FeatureOperation.READ)
    entry = AnimalHealthEntry.all_objects.filter(
        organization_id=context.organization_id, id=entry_id
    ).first()
    if entry is None or str(media_id) not in {str(item) for item in entry.photos}:
        raise NotFound("Nie ma takiego zdjęcia.")
    owner = entry.author_organization_id or context.organization_id
    if owner == context.organization_id:
        return read_media_preview(asset_id=media_id)
    animal = Animal.all_objects.filter(
        organization_id=context.organization_id, id=entry.animal_id
    ).first()
    if animal is None or not _share_with(context.organization_id, animal.farm_id, owner):
        raise NotFound("Nie ma takiego zdjęcia.")
    with transaction.atomic(), _as_owner(owner):
        return read_media_preview(asset_id=media_id)


def _share_with(registry_organization_id: UUID, registry_farm_id: UUID, company: UUID) -> bool:
    """Czy ta firma nadal obsługuje to gospodarstwo."""
    return FarmShare.objects.filter(
        registry_organization_id=registry_organization_id,
        registry_farm_id=registry_farm_id,
        company_organization_id=company,
        status=ShareStatus.ACTIVE,
    ).exists()


@contextmanager
def _as_owner(organization_id: UUID) -> Iterator[None]:
    """Magazyn autora, na czas odczytu jednego podglądu.

    Drugi kierunek tych samych drzwi: `registry_door` wpuszcza firmę do
    rejestru, to wpuszcza rejestr do mediów firmy — z jednym uprawnieniem i z
    przywróceniem organizacji wywołującego, bo `SET LOCAL` żyje do końca
    transakcji, nie do końca bloku.
    """
    caller = require_tenant_context()
    context = TenantContext(
        organization_id=organization_id,
        membership_id=caller.membership_id,
        actor_id=caller.actor_id,
        role_key="farm_share",
        permissions=frozenset({MEDIA_READ}),
        principal_kind="farm_share",
    )
    with activate_tenant_context(context):
        set_local_organization_id(organization_id)
        try:
            yield
        finally:
            with suppress(DatabaseError):
                set_local_organization_id(caller.organization_id)


def registry_health_entries(animal_id: UUID) -> list[AnimalHealthEntry]:
    """The animal's file in the farmer's register, when the share is active.

    This is the other direction of ADR-051 pt 8: the company that works on the
    animal reads what everyone else recorded about it — the keeper's notes, the
    other companies' entries, the vet's — except what the keeper marked private.
    The gate is the share of *this* animal's farm, not of the company, so one
    linked card never opens another farm's file.
    """
    caller = require_tenant_context()
    animal = Animal.all_objects.filter(organization_id=caller.organization_id, id=animal_id).first()
    if animal is None:
        return []
    share = share_for_publishing(caller.organization_id, animal.farm_id)
    if share is None:
        return []
    with transaction.atomic(), registry_door(share, permission=FARMS_READ) as context:
        mirrored = _registry_animal(context, share, animal)
        if mirrored is None:
            return []
        entries = list(
            AnimalHealthEntry.all_objects.filter(
                organization_id=context.organization_id, animal=mirrored, private=False
            )[:PAGE_LIMIT]
        )
    for entry in entries:
        # The company reads its own animal: the registry's id would be an
        # identifier it cannot resolve.
        entry.animal_id = animal.id
        entry.author_is_external = entry.author_organization_id != caller.organization_id
    return entries


def _registry_animal(context: TenantContext, share: FarmShare, animal: Animal) -> Animal | None:
    """The same cow in the register: matched by species and tag, one rule."""
    return Animal.all_objects.filter(
        organization_id=context.organization_id,
        farm_id=share.registry_farm_id,
        species=animal.species,
        national_id=animal.national_id,
    ).first()


def registry_farm_id(organization_id: UUID, farm_id: UUID) -> UUID | None:
    """The farm in the register this card writes into, if it writes anywhere."""
    share = share_for_writing(organization_id, farm_id)
    return share.registry_farm_id if share is not None else None


def publish_farm_visit(
    *,
    company_organization_id: UUID,
    company_farm_id: UUID,
    source: str,
    reference: str,
    status: str,
    scheduled_for: datetime | None = None,
    occurred_on: date | None = None,
    summary: str = "",
    details: dict[str, Any] | None = None,
) -> FarmVisitEntry | None:
    """One visit of a company in the farmer's register (ADR-052).

    Called while the company's context is active, with its own farm; the share
    points at the counterpart in the register. Publishing the same reference
    again rewrites the one row, so a visit moves from planned to done — and to
    cancelled, which stays: a visit called off is a fact the keeper may keep.

    Returns None when nobody shares this card, which is the ordinary case.

    `details` must already be readable: the register renders labels and values
    and may not import a vertical to resolve its codes, because the layer
    contract puts verticals above shared.
    """
    share = share_for_schedule(company_organization_id, company_farm_id)
    if share is None:
        return None
    with transaction.atomic(), registry_door(share) as context:
        farm = Farm.all_objects.filter(
            organization_id=context.organization_id, id=share.registry_farm_id
        ).first()
        if farm is None:
            # The keeper deleted the farm the share points at; the share is
            # stale and the company's own record already stands.
            return None
        entry, _ = FarmVisitEntry.all_objects.update_or_create(
            organization_id=context.organization_id,
            farm=farm,
            company_organization_id=share.company_organization_id,
            source=source,
            source_reference=reference,
            defaults={
                "company_name": share.company_name,
                "status": status,
                "scheduled_for": scheduled_for,
                "occurred_on": occurred_on,
                "summary": summary,
                "details": details or {},
            },
        )
        return entry


def list_farm_visits(farm_id: UUID, *, limit: int = PAGE_LIMIT) -> list[FarmVisitEntry]:
    """What the keeper sees about one farm of their own register.

    A visit still marked planned by a company whose share is gone is hidden, not
    deleted: after a revocation the door is shut, so that company can never move
    the row off `planned`, and a visit that will never happen would otherwise
    sit in the future for ever. What already happened — done, cancelled — stays,
    because that is history and history does not depend on today's consent
    (ADR-052 pt 8 and 9).
    """
    context = authorize_entitled(FARMS_READ, FARMS_ENABLED, operation=FeatureOperation.READ)
    # Which companies may still show a future date here. Asked before the page
    # is cut, not after: filtering a page already sliced to `limit` hands back
    # fewer rows than asked for while more were waiting behind them.
    allowed = FarmShare.objects.filter(
        registry_organization_id=context.organization_id,
        registry_farm_id=farm_id,
        status=ShareStatus.ACTIVE,
    ).values_list("company_organization_id", flat=True)
    return list(
        FarmVisitEntry.all_objects.filter(
            organization_id=context.organization_id, farm_id=farm_id
        ).filter(~Q(status=VisitStatus.PLANNED) | Q(company_organization_id__in=allowed))[:limit]
    )
