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
        carried_from: UUID | None = None,
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
        # An asset the earlier owner references is already in use: deleting it
        # only tombstones it, and its file stays while any publication points
        # at it, so carrying it over is safe and must not fail.
        carried = (
            set(
                MediaReference.all_objects.filter(
                    organization_id=context.organization_id,
                    owner_type=owner_type,
                    owner_id=carried_from,
                    asset_id__in=resource_ids,
                ).values_list("asset_id", flat=True)
            )
            if carried_from is not None
            else set()
        )
        new_ids = tuple(asset_id for asset_id in resource_ids if asset_id not in carried)
        ready_ids = tuple(
            MediaAsset.all_objects.select_for_update()
            .filter(
                organization_id=context.organization_id,
                id__in=new_ids,
                state=MediaAssetState.READY,
                deleted_at__isnull=True,
            )
            .order_by("id")
            .values_list("id", flat=True)
        )
        if set(ready_ids) != set(new_ids):
            raise ResourceReferenceRejected
        MediaReference.all_objects.bulk_create([
            MediaReference(
                organization_id=context.organization_id,
                asset_id=asset_id,
                owner_type=owner_type,
                owner_id=owner_id,
            )
            for asset_id in resource_ids
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

    @transaction.atomic
    def copy(
        self,
        *,
        context: TenantContext,
        owner_type: str,
        source_owner_id: UUID,
        target_owner_id: UUID,
    ) -> tuple[UUID, ...]:
        if owner_type not in MediaReferenceOwner.values:
            raise ResourceReferenceRejected
        source_ids = tuple(
            MediaReference.all_objects.select_for_update()
            .filter(
                organization_id=context.organization_id,
                owner_type=owner_type,
                owner_id=source_owner_id,
            )
            .order_by("asset_id")
            .values_list("asset_id", flat=True)
        )
        existing_ids = tuple(
            MediaReference.all_objects.select_for_update()
            .filter(
                organization_id=context.organization_id,
                owner_type=owner_type,
                owner_id=target_owner_id,
            )
            .order_by("asset_id")
            .values_list("asset_id", flat=True)
        )
        if existing_ids:
            if existing_ids != source_ids:
                raise ResourceReferenceConflict
            return existing_ids
        MediaReference.all_objects.bulk_create([
            MediaReference(
                organization_id=context.organization_id,
                asset_id=asset_id,
                owner_type=owner_type,
                owner_id=target_owner_id,
            )
            for asset_id in source_ids
        ])
        return source_ids


media_asset_reference_handler = MediaAssetReferenceHandler()
