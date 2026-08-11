from __future__ import annotations

from uuid import UUID

from django.db import transaction

from saas_core.modules.core.organizations.api import (
    ResourceReferenceConflict,
    ResourceReferenceRejected,
)
from saas_core.modules.core.organizations.context import TenantContext

from .models import MediaAsset, MediaAssetState, MediaReference, MediaReferenceOwner

MEDIA_ASSET_RESOURCE_TYPE = "shared.media.asset"


class MediaAssetReferenceHandler:
    @transaction.atomic
    def record(
        self,
        *,
        context: TenantContext,
        owner_type: str,
        owner_id: UUID,
        resource_ids: tuple[UUID, ...],
    ) -> tuple[UUID, ...]:
        if owner_type not in MediaReferenceOwner.values:
            raise ResourceReferenceRejected
        existing_ids = tuple(
            MediaReference.all_objects.select_for_update()
            .filter(
                organization_id=context.organization_id,
                owner_type=owner_type,
                owner_id=owner_id,
            )
            .order_by("asset_id")
            .values_list("asset_id", flat=True)
        )
        if existing_ids:
            if existing_ids != resource_ids:
                raise ResourceReferenceConflict
            return existing_ids
        if not resource_ids:
            return ()
        ready_assets = list(
            MediaAsset.all_objects.select_for_update()
            .filter(
                organization_id=context.organization_id,
                id__in=resource_ids,
                state=MediaAssetState.READY,
                deleted_at__isnull=True,
            )
            .order_by("id")
        )
        if tuple(asset.id for asset in ready_assets) != resource_ids:
            raise ResourceReferenceRejected
        MediaReference.all_objects.bulk_create([
            MediaReference(
                organization_id=context.organization_id,
                asset=asset,
                owner_type=owner_type,
                owner_id=owner_id,
            )
            for asset in ready_assets
        ])
        return resource_ids

    def list_ids(
        self,
        *,
        context: TenantContext,
        owner_type: str,
        owner_id: UUID,
    ) -> tuple[UUID, ...]:
        if owner_type not in MediaReferenceOwner.values:
            raise ResourceReferenceRejected
        return tuple(
            MediaReference.all_objects.filter(
                organization_id=context.organization_id,
                owner_type=owner_type,
                owner_id=owner_id,
            )
            .order_by("asset_id")
            .values_list("asset_id", flat=True)
        )


media_asset_reference_handler = MediaAssetReferenceHandler()
