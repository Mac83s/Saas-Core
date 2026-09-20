"""Allowlisted demonstration photos use the ordinary tenant media lifecycle."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import NotFound

from saas_core.modules.shared.billing.api import authorize_entitled
from saas_core.modules.shared.media.api import materialize_approved_media_asset

from .page_templates import _approved_media, _read_json
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED
from .services import _idempotency_key


@transaction.atomic
def materialize_template_photo(*, photo_id: str, idempotency_key: str) -> UUID:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    key = _idempotency_key(idempotency_key)
    directory = Path(settings.PAGE_TEMPLATE_CONTRACTS_PATH)
    catalog = _read_json(directory / "sample-media.v1.json")
    photo = next((item for item in catalog["media"] if item["id"] == photo_id), None)
    if photo is None:
        raise NotFound("Nie znaleziono zdjęcia szablonu.", code="template_photo_not_found")
    (medium,) = _approved_media(contract_directory=directory, recipe={"media": [photo]})
    result = materialize_approved_media_asset(
        source_key="template-photo:"
        + hashlib.sha256(f"{context.actor_id}:{key}".encode()).hexdigest(),
        filename=medium.filename,
        content_type=medium.content_type,
        content=medium.read(),
    )
    return result.asset.id
