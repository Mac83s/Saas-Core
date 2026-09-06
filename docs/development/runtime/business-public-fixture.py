"""Synthetic local fixture for public delivery, executed inside a business backend.

Requires SEO_RUNTIME_SMOKE=synthetic-local and APP_ENV=local. This deliberately
seeds a verified domain and a ready image; it does not test DNS, onboarding or
malware scanning. Publication itself goes through the person-only domain service.
Only public fixture identifiers are printed; no password, session or secret leaves
the container. Each invocation creates a fresh, separately named organization.
"""

import hashlib
import io
import json
import os
import uuid
from datetime import timedelta

import django

assert os.environ.get("SEO_RUNTIME_SMOKE") == "synthetic-local"
assert os.environ.get("APP_ENV") == "local"
assert os.environ.get("DEPLOYMENT") == "business"
django.setup()

from django.db import connection, transaction  # noqa: E402
from django.utils import timezone  # noqa: E402
from PIL import Image  # noqa: E402

from saas_core.modules.core.identity.models import User  # noqa: E402
from saas_core.modules.core.organizations.context import (  # noqa: E402
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (  # noqa: E402
    Membership,
    Organization,
    Role,
)
from saas_core.modules.shared.billing.models import EntitlementSnapshot  # noqa: E402
from saas_core.modules.shared.media.models import MediaAsset  # noqa: E402
from saas_core.modules.shared.media.storage import S3ObjectStorage  # noqa: E402
from saas_core.modules.shared.sites.models import Domain  # noqa: E402
from saas_core.modules.shared.sites.services import (  # noqa: E402
    create_page,
    create_site,
    publish_site,
    save_draft,
    save_page_translation,
)

organization_id = uuid.uuid7()
label = "seo-public-smoke-" + organization_id.hex[-12:]
host = label + ".example.test"
heading = "Synthetic public delivery " + label
buffer = io.BytesIO()
Image.new("RGB", (64, 48), color=(24, 96, 180)).save(buffer, "PNG")
content = buffer.getvalue()
storage = S3ObjectStorage()
try:
    storage.private_client.create_bucket(Bucket=storage.bucket)
except storage.private_client.exceptions.BucketAlreadyOwnedByYou:
    pass

with transaction.atomic():
    set_local_organization_id(organization_id)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
        )
        db_role, superuser, bypass_rls = cursor.fetchone()
        assert not superuser and not bypass_rls
    user = User.objects.create_user(
        email=label + "@example.test", password=None, status="active"
    )
    organization = Organization.objects.create(
        id=organization_id, name=label, slug=label, status="active"
    )
    membership = Membership.objects.create(
        organization=organization,
        user=user,
        role=Role.objects.get(key="owner", organization_id=None),
    )
    EntitlementSnapshot.all_objects.create(
        organization=organization,
        subscription_state="active",
        access_mode="full",
        features={"sites.enabled": True, "media.enabled": True},
        quotas={"sites.max": 5, "media.storage_bytes": 1000000},
        sources={},
    )
    with activate_tenant_context(context_from_membership(membership)):
        site = create_site(
            name=label, slug=label, default_locale="pl", idempotency_key=label
        ).value
        page = create_page(
            site_id=site.id, name="Start", key="home", idempotency_key=label
        ).value
        asset_id = uuid.uuid7()
        object_key = f"{organization_id}/processed/{asset_id}/fixture.png"
        storage.put(object_key=object_key, content=content, content_type="image/png")
        asset = MediaAsset.all_objects.create(
            id=asset_id,
            organization=organization,
            original_filename="fixture.png",
            object_key=object_key,
            declared_mime="image/png",
            detected_mime="image/png",
            expected_size=len(content),
            actual_size=len(content),
            stored_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            width=64,
            height=48,
            state="ready",
            quota_reservation_key=str(asset_id),
            quota_committed=True,
            upload_expires_at=timezone.now() + timedelta(hours=1),
            ready_at=timezone.now(),
            created_by=user,
            idempotency_key=str(asset_id),
            request_hash="0" * 64,
        )
        save_draft(
            page_id=page.id,
            expected_version=0,
            idempotency_key=label,
            media_asset_ids=[asset.id],
            blocks=[
                {
                    "block_type": "core.hero",
                    "schema_version": 3,
                    "data": {
                        "title": heading,
                        "text": "No external provider was called.",
                        "image": {
                            "asset_id": str(asset.id),
                            "alt": "Synthetic blue fixture",
                        },
                    },
                }
            ],
        )
        save_page_translation(
            page_id=page.id,
            locale="pl",
            expected_version=0,
            slug="start",
            title=heading,
            description="Local runtime publication smoke test",
            social_title=heading,
            social_description="Local runtime publication smoke test",
            allow_title_fallback=False,
            allow_description_fallback=False,
            allow_social_title_fallback=False,
            allow_social_description_fallback=False,
            idempotency_key=label,
        )
        Domain.all_objects.filter(
            site=site, organization=organization, is_canonical=True
        ).update(is_canonical=False)
        Domain.all_objects.create(
            organization=organization,
            site=site,
            hostname=host,
            kind="custom",
            status="verified",
            is_canonical=True,
            created_by=user,
        )
        publication = publish_site(site_id=site.id, idempotency_key=label).publication

print(
    json.dumps(
        {
            "organization_id": str(organization_id),
            "site_id": str(site.id),
            "publication_id": str(publication.id),
            "publication_hash": publication.snapshot_hash,
            "host": host,
            "path": "/start/",
            "heading": heading,
            "image_path": f"/media/{asset.id}",
            "image_api_path": f"/api/v1/public/site/media/{asset.id}/",
            "image_sha256": asset.sha256,
            "image_bytes": len(content),
            "database_role": db_role,
            "superuser": superuser,
            "bypass_rls": bypass_rls,
            "fixture_limits": [
                "synthetic verified domain",
                "synthetic ready image",
                "no DNS or malware-scanning proof",
                "no real provider calls",
            ],
        }
    )
)
