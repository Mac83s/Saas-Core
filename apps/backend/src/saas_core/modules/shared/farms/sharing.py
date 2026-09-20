"""Sharing a farm between a company's card and the farmer's register (ADR-051).

Two tenants, one herd: the company records a farm as its card before the farmer
has an account, and the farmer later takes the herd over with an activation code
the company hands them. From then on the register is the source of truth and the
company keeps its card, with the scope the farmer sees and can revoke.

Neither side may read the other's rows: row-level security is per tenant, and
the door from ADR-041 opens no table of this module. So the handover travels in
the code itself — `issue_activation_code` copies the card and its animals while
the company's own context is active, and `redeem_activation_code` reads only
that copy. A green test would not have caught this: the test database connects
as the table owner and sees every tenant.

`FarmActivationCode` and `FarmShare` (models.py) are cross-tenant by nature,
like booking's self-service route: they name organizations by id and carry no
foreign key to `Organization`, so no row-level policy can express "mine". Every
read and write goes through the use cases here, which filter by the caller's
organization — nothing else may touch them.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, ValidationError

from saas_core.modules.core.organizations.models import Organization, OrganizationAuditAction
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .models import (
    Animal,
    Farm,
    FarmActivationCode,
    FarmShare,
    ShareBasis,
    ShareStatus,
)
from .services import FARMS_ENABLED, FARMS_MANAGE, FARMS_READ, audit_farm

#: Long enough for a printed report to reach the farmer, short enough that a
#: code left on a desk stops working.
CODE_TTL = timedelta(days=30)


class Conflict(APIException):
    status_code = 409
    default_detail = "Stan gospodarstwa nie pozwala na tę operację."
    default_code = "farm_already_linked"


#: Five groups of four, easy to read out over the phone and to type in a barn.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_GROUPS = 4
CODE_GROUP_SIZE = 4


def issue_code() -> tuple[str, str]:
    groups = [
        "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_GROUP_SIZE))
        for _ in range(CODE_GROUPS)
    ]
    code = "-".join(groups)
    return code, code_digest(code)


def code_digest(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode()).hexdigest()


def normalize_code(code: str) -> str:
    """How a code is typed differs; how it is matched does not."""
    cleaned = "".join(ch for ch in code.upper() if ch.isalnum())
    return "-".join(
        cleaned[index : index + CODE_GROUP_SIZE]
        for index in range(0, len(cleaned), CODE_GROUP_SIZE)
    )


# --- use cases ---------------------------------------------------------------


@transaction.atomic
def issue_activation_code(*, request: HttpRequest, farm_id: UUID) -> tuple[str, datetime]:
    """A code the company hands the farmer for one of its cards (ADR-051 pt 5).

    The previous unused code for the card stops working: a code lying around on
    a printout is a way into somebody's herd.
    """
    context = authorize_entitled(FARMS_MANAGE, FARMS_ENABLED)
    farm = Farm.all_objects.filter(organization_id=context.organization_id, id=farm_id).first()
    if farm is None:
        raise NotFound("Nie ma takiego gospodarstwa.")
    if _share_of_card(context.organization_id, farm.id) is not None:
        raise Conflict("To gospodarstwo jest już połączone z kontem rolnika.")
    FarmActivationCode.objects.filter(
        company_organization_id=context.organization_id, farm_id=farm.id, used_at__isnull=True
    ).delete()
    code, digest = issue_code()
    expires_at = timezone.now() + CODE_TTL
    FarmActivationCode.objects.create(
        token_digest=digest,
        company_organization_id=context.organization_id,
        company_name=_organization_name(context.organization_id),
        handover=_handover(farm),
        farm_id=farm.id,
        created_by_id=context.actor_id,
        expires_at=expires_at,
    )
    audit_farm(request, context.organization_id, OrganizationAuditAction.FARM_CODE_ISSUED, farm)
    return code, expires_at


@transaction.atomic
def redeem_activation_code(*, request: HttpRequest, code: str) -> dict[str, Any]:
    """The farmer takes the herd over: the card becomes their farm, the company
    keeps its copy and the share that says what it may still do."""
    context = authorize_entitled(FARMS_MANAGE, FARMS_ENABLED)
    entry = (
        FarmActivationCode.objects.select_for_update()
        .filter(token_digest=code_digest(code))
        .first()
    )
    if entry is None or entry.used_at is not None or entry.expires_at <= timezone.now():
        # One answer for "no such code", "used" and "expired": a code is a secret.
        raise ValidationError({"code": "Kod jest nieprawidłowy albo stracił ważność."})
    if entry.company_organization_id == context.organization_id:
        raise ValidationError({"code": "To kod tej samej organizacji."})
    card = entry.handover.get("farm") or {}
    farm, created = _farm_of_registry(context.organization_id, card, request)
    copied = _copy_animals(context.organization_id, entry.handover.get("animals", []), farm)
    # A farmer who revoked and links again keeps the same row: the pair is
    # unique, and the share is the relationship, not one episode of it.
    share, _ = FarmShare.objects.update_or_create(
        registry_farm_id=farm.id,
        company_farm_id=entry.farm_id,
        defaults={
            "registry_organization_id": context.organization_id,
            "company_organization_id": entry.company_organization_id,
            "company_name": entry.company_name,
            "registry_name": _organization_name(context.organization_id),
            "basis": ShareBasis.ACTIVATION_CODE,
            "status": ShareStatus.ACTIVE,
            "granted_at": timezone.now(),
            "revoked_at": None,
        },
    )
    _name_partner(share, context.organization_id)
    entry.used_at = timezone.now()
    entry.used_by_organization_id = context.organization_id
    entry.save(update_fields=["used_at", "used_by_organization_id"])
    audit_farm(request, context.organization_id, OrganizationAuditAction.FARM_TAKEN_OVER, farm)
    audit_farm(request, context.organization_id, OrganizationAuditAction.FARM_SHARE_GRANTED, farm)
    return {"farm": farm, "created": created, "animals_added": copied, "share": share}


def list_shares(*, farm_id: UUID) -> list[FarmShare]:
    """Who the farmer's farm is shared with; the company sees its own side.

    Each row carries the other side's name and which side that is, because a
    panel showing two organization ids says nothing to the person reading it.
    """
    context = authorize_entitled(FARMS_READ, FARMS_ENABLED, operation=FeatureOperation.READ)
    shares = list(
        FarmShare.objects.filter(
            Q(registry_organization_id=context.organization_id, registry_farm_id=farm_id)
            | Q(company_organization_id=context.organization_id, company_farm_id=farm_id)
        )
    )
    for share in shares:
        _name_partner(share, context.organization_id)
    return shares


@transaction.atomic
def revoke_share(*, request: HttpRequest, share_id: UUID) -> FarmShare:
    """The farmer stops the sharing; the company keeps its card as it stands."""
    context = authorize_entitled(FARMS_MANAGE, FARMS_ENABLED)
    share = (
        FarmShare.objects.select_for_update()
        .filter(pk=share_id, registry_organization_id=context.organization_id)
        .first()
    )
    if share is None:
        raise NotFound("Nie ma takiego udostępnienia.")
    if share.status == ShareStatus.ACTIVE:
        share.status = ShareStatus.REVOKED
        share.revoked_at = timezone.now()
        share.save(update_fields=["status", "revoked_at"])
        farm = Farm.all_objects.get(
            organization_id=context.organization_id, id=share.registry_farm_id
        )
        audit_farm(
            request, context.organization_id, OrganizationAuditAction.FARM_SHARE_REVOKED, farm
        )
    _name_partner(share, context.organization_id)
    return share


def share_for_writing(company_organization_id: UUID, company_farm_id: UUID) -> FarmShare | None:
    """The active share a company may write the herd through, if it has one."""
    share = _share_of_card(company_organization_id, company_farm_id)
    return share if share is not None and share.can_write_herd else None


def _share_of_card(company_organization_id: UUID, company_farm_id: UUID) -> FarmShare | None:
    return FarmShare.objects.filter(
        company_organization_id=company_organization_id,
        company_farm_id=company_farm_id,
        status=ShareStatus.ACTIVE,
    ).first()


#: What a card hands over. The company's private note is not here: it stays
#: with the company (ADR-051 pt 2).
HANDOVER_FARM_FIELDS = (
    "name",
    "herd_number",
    "tax_id",
    "village",
    "address",
    "keeper_name",
    "email",
    "phone",
    "housing",
)
HANDOVER_ANIMAL_FIELDS = (
    "species",
    "national_id",
    "working_number",
    "name",
    "sex",
    "birth_date",
    "status",
)


def _handover(farm: Farm) -> dict[str, Any]:
    """The card as the farmer will receive it, read while the company's own
    tenant context is active."""
    return {
        "farm": {field: getattr(farm, field) for field in HANDOVER_FARM_FIELDS},
        "animals": [
            {
                field: value.isoformat() if isinstance(value, date) else value
                for field, value in animal.items()
            }
            for animal in Animal.all_objects.filter(
                organization_id=farm.organization_id, farm=farm
            ).values(*HANDOVER_ANIMAL_FIELDS)
        ],
    }


def _organization_name(organization_id: UUID) -> str:
    """The caller's own organization — the only one its tenant may read."""
    return (
        Organization.objects.filter(id=organization_id).values_list("name", flat=True).first() or ""
    )


def _name_partner(share: FarmShare, organization_id: UUID) -> None:
    share.partner_is_company = share.registry_organization_id == organization_id
    share.partner_name = share.company_name if share.partner_is_company else share.registry_name


def _farm_of_registry(
    organization_id: UUID, card: dict[str, Any], request: HttpRequest
) -> tuple[Farm, bool]:
    """The farmer's own farm: the one with this herd number, or a copy of the card."""
    herd_number = card.get("herd_number", "")
    if herd_number:
        existing = Farm.all_objects.filter(
            organization_id=organization_id, herd_number=herd_number
        ).first()
        if existing is not None:
            return existing, False
    given = card.get("name") or "Gospodarstwo"
    name = given
    for suffix in range(2, 50):
        if not Farm.all_objects.filter(organization_id=organization_id, name=name).exists():
            break
        name = f"{given} ({suffix})"
    farm = Farm.all_objects.create(
        organization_id=organization_id,
        **{field: card.get(field, "") for field in HANDOVER_FARM_FIELDS if field != "name"},
        name=name,
    )
    audit_farm(request, organization_id, OrganizationAuditAction.FARM_CREATED, farm)
    return farm, True


def _copy_animals(organization_id: UUID, animals: list[dict[str, Any]], farm: Farm) -> int:
    """Animals of the card the register does not have yet, matched by tag."""
    known = set(
        Animal.all_objects.filter(organization_id=organization_id, farm=farm).values_list(
            "species", "national_id"
        )
    )
    missing = [
        Animal(organization_id=organization_id, farm=farm, **animal)
        for animal in animals
        if (animal.get("species"), animal.get("national_id")) not in known
    ]
    Animal.all_objects.bulk_create(missing)
    return len(missing)
