from __future__ import annotations

import json
from functools import cache
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from rest_framework.exceptions import APIException, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .models import Site, SiteAppearanceRevision, canonical_json_hash
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED
from .services import (
    DEFAULT_DESIGN_TOKENS,
    SiteNotFound,
    SitesIdempotencyConflict,
    _idempotency_key,
    assert_person_required,
)


class AppearanceVersionConflict(APIException):
    status_code = 409
    default_code = "site_appearance_version_conflict"
    default_detail = "Wygląd witryny został zmieniony. Wczytaj aktualną wersję."


def default_appearance(site: Site) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "designTokens": dict(DEFAULT_DESIGN_TOKENS),
        "font": "system",
        "width": "standard",
        "buttons": "solid",
        "header": {"layout": "none", "brand": site.name, "tagline": ""},
        "footer": {"layout": "none", "text": "", "links": []},
        "navigation": {"mobile": "drawer", "tablet": "drawer"},
    }


@cache
def appearance_validator() -> Draft202012Validator:
    directory = settings.SITE_BLOCK_CONTRACTS_PATH
    tokens = json.loads((directory / "design-tokens.v1.schema.json").read_text())
    schema = {
        "anyOf": [
            json.loads((directory / f"site-appearance.v{version}.schema.json").read_text())
            for version in (1, 2)
        ]
    }
    registry = Registry().with_resource(tokens["$id"], Resource.from_contents(tokens))
    return Draft202012Validator(schema, registry=registry)


def validate_appearance(data: dict[str, Any]) -> dict[str, Any]:
    if not appearance_validator().is_valid(data):
        raise ValidationError({"appearance": "Ustawienia wyglądu nie spełniają schematu."})
    return data


def _latest(site: Site) -> SiteAppearanceRevision | None:
    context = require_tenant_context()
    return SiteAppearanceRevision.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site.id,
    ).first()


def appearance_snapshot(site: Site) -> dict[str, Any] | None:
    revision = _latest(site)
    return revision.data if revision else None


def get_site_appearance(*, site_id: UUID) -> dict[str, Any]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ)
    site = Site.all_objects.filter(id=site_id, organization_id=context.organization_id).first()
    if site is None:
        raise SiteNotFound()
    revision = _latest(site)
    return {
        "site_id": site.id,
        "version": revision.number if revision else 0,
        "appearance": revision.data if revision else default_appearance(site),
    }


@transaction.atomic
def save_site_appearance(
    *, site_id: UUID, expected_version: int, appearance: dict[str, Any], idempotency_key: str
) -> dict[str, Any]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, "Wygląd i nawigacja witryny")
    key = _idempotency_key(idempotency_key)
    validate_appearance(appearance)
    site = (
        Site.all_objects.select_for_update()
        .filter(
            id=site_id,
            organization_id=context.organization_id,
        )
        .first()
    )
    if site is None:
        raise SiteNotFound()
    request_hash = canonical_json_hash({
        "expected_version": expected_version,
        "appearance": appearance,
    })
    existing = SiteAppearanceRevision.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site_id,
        created_by_id=context.actor_id,
        idempotency_key=key,
    ).first()
    if existing:
        if existing.request_hash != request_hash:
            raise SitesIdempotencyConflict()
        return {"site_id": site.id, "version": existing.number, "appearance": existing.data}
    previous = _latest(site)
    if (previous.number if previous else 0) != expected_version:
        raise AppearanceVersionConflict()
    revision = SiteAppearanceRevision.all_objects.create(
        organization_id=context.organization_id,
        site=site,
        number=expected_version + 1,
        data=appearance,
        created_by_id=context.actor_id,
        idempotency_key=key,
        request_hash=request_hash,
    )
    record_audit(
        organization=Organization.objects.get(id=context.organization_id),
        actor=User.objects.get(id=context.actor_id),
        action="sites.appearance.saved",
        target_type="site",
        target_id=site.id,
        metadata={"appearance_version": revision.number},
    )
    return {"site_id": site.id, "version": revision.number, "appearance": revision.data}
