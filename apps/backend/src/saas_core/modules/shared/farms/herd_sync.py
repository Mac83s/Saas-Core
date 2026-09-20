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

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import date
from typing import Any
from uuid import UUID

from django.db import DatabaseError, transaction
from django.http import HttpRequest
from django.utils import timezone
from rest_framework.exceptions import NotFound

from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    require_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import OrganizationAuditAction
from saas_core.modules.shared.billing.api import authorize_entitled

from .models import Animal, AnimalHealthEntry, AnimalStatus, Farm, FarmShare, HealthEntryKind
from .services import FARMS_ENABLED, FARMS_MANAGE, FARMS_READ, PAGE_LIMIT, audit_farm
from .sharing import Conflict, share_for_publishing, share_for_writing

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
) -> AnimalHealthEntry | None:
    """One entry in the farmer's register about an animal (ADR-051 pt 8).

    Called by a vertical while the company's context is active; the animal is
    the company's own, and its counterpart in the register is found by tag.
    The entry names its author and its day, so it is its own audit trail.
    Publishing the same source reference twice rewrites the one row, so a
    corrected visit corrects the history instead of doubling it.
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
        entry, _ = AnimalHealthEntry.all_objects.update_or_create(
            organization_id=context.organization_id,
            animal=mirrored,
            source=source,
            source_reference=reference,
            defaults={
                "kind": kind,
                "occurred_on": occurred_on,
                "author_name": author_name or share.company_name,
                "author_organization_id": share.company_organization_id,
                "author_organization_name": share.company_name,
                "summary": summary,
                "details": details or {},
            },
        )
        return entry


def registry_health_entries(animal_id: UUID) -> list[AnimalHealthEntry]:
    """The animal's file in the farmer's register, when the share is active.

    This is the other direction of ADR-051 pt 8: the company that works on the
    animal reads what everyone else recorded about it — the keeper's notes, the
    other companies' entries, the vet's — except what the keeper marked private.
    The gate is the share of *this* animal's farm, not of the company, so one
    linked card never opens another farm's file.
    """
    caller = require_tenant_context()
    animal = Animal.all_objects.filter(
        organization_id=caller.organization_id, id=animal_id
    ).first()
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


def _registry_animal(
    context: TenantContext, share: FarmShare, animal: Animal
) -> Animal | None:
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
