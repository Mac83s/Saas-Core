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
from contextlib import contextmanager
from datetime import date
from typing import Any
from uuid import UUID

from django.db import transaction
from django.http import HttpRequest

from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    require_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import OrganizationAuditAction

from .models import Animal, AnimalHealthEntry, Farm, FarmShare
from .services import FARMS_MANAGE, audit_farm
from .sharing import share_for_publishing, share_for_writing

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
def registry_writer(share: FarmShare) -> Iterator[TenantContext]:
    """The farmer's tenant, for the statements the share allows."""
    caller = require_tenant_context()
    context = TenantContext(
        organization_id=share.registry_organization_id,
        membership_id=caller.membership_id,
        actor_id=caller.actor_id,
        role_key="farm_share",
        permissions=frozenset({FARMS_MANAGE}),
        principal_kind="farm_share",
    )
    with activate_tenant_context(context):
        set_local_organization_id(context.organization_id)
        try:
            yield context
        finally:
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
    values: dict[str, Any] = {field: getattr(animal, field) for field in SYNCED_FIELDS}
    with transaction.atomic(), registry_writer(share) as context:
        farm = Farm.all_objects.filter(
            organization_id=context.organization_id, id=share.registry_farm_id
        ).first()
        if farm is None:
            # The farmer deleted the farm the share points at; the share is
            # stale and the company's own record already stands.
            return None
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


def publish_health_entry(
    request: HttpRequest,
    *,
    animal: Animal,
    occurred_on: date,
    source: str,
    reference: str,
    summary: str,
    details: dict[str, Any] | None = None,
) -> AnimalHealthEntry | None:
    """One entry in the farmer's register about an animal (ADR-051 pt 8).

    Called by a vertical while the company's context is active; the animal is
    the company's own, and its counterpart in the register is found by tag.
    Publishing the same source reference twice rewrites the one row, so a
    corrected visit corrects the history instead of doubling it.
    """
    share = share_for_publishing(animal.organization_id, animal.farm_id)
    if share is None:
        return None
    with transaction.atomic(), registry_writer(share) as context:
        mirrored = Animal.all_objects.filter(
            organization_id=context.organization_id,
            farm_id=share.registry_farm_id,
            species=animal.species,
            national_id=animal.national_id,
        ).first()
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
                "occurred_on": occurred_on,
                "author_name": share.company_name,
                "author_organization_id": share.company_organization_id,
                "summary": summary,
                "details": details or {},
            },
        )
        return entry


def registry_farm_id(organization_id: UUID, farm_id: UUID) -> UUID | None:
    """The farm in the register this card writes into, if it writes anywhere."""
    share = share_for_writing(organization_id, farm_id)
    return share.registry_farm_id if share is not None else None
