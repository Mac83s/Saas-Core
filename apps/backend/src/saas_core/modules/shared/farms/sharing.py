"""Sharing a farm between a company's card and the farmer's register (ADR-051).

Two tenants, one herd: the company records a farm as its card before the farmer
has an account, and the farmer later takes the herd over with an activation code
the company hands them. From then on the register is the source of truth and the
company keeps its card, with the scope the farmer sees and can revoke.

`FarmActivationCode` and `FarmShare` (models.py) are cross-tenant by nature,
like booking's self-service route: they name organizations by id and carry no
foreign key to `Organization`, so no row-level policy can express "mine". Every
read and write goes through the use cases here, which filter by the caller's
organization — nothing else may touch them.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
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
    card = Farm.all_objects.filter(
        organization_id=entry.company_organization_id, id=entry.farm_id
    ).first()
    if card is None:
        raise ValidationError({"code": "Gospodarstwo z tego kodu już nie istnieje."})
    farm, created = _farm_of_registry(context.organization_id, card, request)
    copied = _copy_animals(context.organization_id, card, farm)
    share = FarmShare.objects.create(
        registry_organization_id=context.organization_id,
        registry_farm_id=farm.id,
        company_organization_id=entry.company_organization_id,
        company_farm_id=card.id,
        basis=ShareBasis.ACTIVATION_CODE,
    )
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
    partner_ids = {
        share.company_organization_id
        if share.registry_organization_id == context.organization_id
        else share.registry_organization_id
        for share in shares
    }
    names = dict(
        Organization.objects.filter(id__in=partner_ids).values_list("id", "name")
    )
    for share in shares:
        share.partner_is_company = share.registry_organization_id == context.organization_id
        partner = (
            share.company_organization_id
            if share.partner_is_company
            else share.registry_organization_id
        )
        share.partner_name = names.get(partner, "")
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
    # The caller is the registry side here, so the partner is the company.
    share.partner_is_company = True
    share.partner_name = (
        Organization.objects.filter(id=share.company_organization_id)
        .values_list("name", flat=True)
        .first()
        or ""
    )
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


def _farm_of_registry(organization_id: UUID, card: Farm, request: HttpRequest) -> tuple[Farm, bool]:
    """The farmer's own farm: the one with this herd number, or a copy of the card.

    Private notes of the company stay with the company (ADR-051 pt 2).
    """
    if card.herd_number:
        existing = Farm.all_objects.filter(
            organization_id=organization_id, herd_number=card.herd_number
        ).first()
        if existing is not None:
            return existing, False
    name = card.name
    for suffix in range(2, 50):
        if not Farm.all_objects.filter(organization_id=organization_id, name=name).exists():
            break
        name = f"{card.name} ({suffix})"
    farm = Farm.all_objects.create(
        organization_id=organization_id,
        name=name,
        herd_number=card.herd_number,
        tax_id=card.tax_id,
        village=card.village,
        address=card.address,
        keeper_name=card.keeper_name,
        email=card.email,
        phone=card.phone,
        housing=card.housing,
    )
    audit_farm(request, organization_id, OrganizationAuditAction.FARM_CREATED, farm)
    return farm, True


def _copy_animals(organization_id: UUID, card: Farm, farm: Farm) -> int:
    """Animals of the card the register does not have yet, matched by tag."""
    known = set(
        Animal.all_objects.filter(organization_id=organization_id, farm=farm).values_list(
            "species", "national_id"
        )
    )
    missing = [
        Animal(
            organization_id=organization_id,
            farm=farm,
            species=animal.species,
            national_id=animal.national_id,
            working_number=animal.working_number,
            name=animal.name,
            sex=animal.sex,
            birth_date=animal.birth_date,
            status=animal.status,
        )
        for animal in Animal.all_objects.filter(organization_id=card.organization_id, farm=card)
        if (animal.species, animal.national_id) not in known
    ]
    Animal.all_objects.bulk_create(missing)
    return len(missing)
