"""Delegated Google access. Core retains consent receipts, never Google tokens or metrics."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import APIException, NotFound, PermissionDenied

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.authorization import authorize as authorize_permission
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.erasure import ErasureBlocked
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled
from saas_core.modules.shared.sites.api import read_site_audit_target

from ..models import SourceSiteBinding
from ..source import SourceConfig, SourceError, SsaSource, canonical_hash
from .models import GscGrantIntent, GscOAuthAttempt, GscSyncIntent, GscWorkspaceState
from .settings import authorization_url, redirect_uri

ENABLED = "seo.gsc.enabled"
READ = "seo.gsc.read"
MANAGE = "seo.gsc.manage"
PREFIX = "/integration/gsc/"
METRIC_FIELDS = (
    "dataset",
    "date",
    "query",
    "page",
    "country",
    "device",
    "search_appearance",
    "clicks",
    "impressions",
    "ctr",
    "position",
)


def _datetime(value: Any) -> datetime | None:
    try:
        return parse_datetime(str(value))
    except ValueError as error:
        raise SourceError("gsc_response_malformed") from error


class GscConflict(APIException):
    status_code = 409
    default_detail = "The Search Console operation changed. Refresh its current state."
    default_code = "gsc_conflict"


def context(*, manage: bool = False, cleanup: bool = False) -> TenantContext:
    value = (
        authorize_permission(MANAGE)
        if cleanup
        else authorize_entitled(
            MANAGE if manage else READ,
            ENABLED,
            operation=FeatureOperation.WRITE if manage else FeatureOperation.READ,
        )
    )
    if value.principal_kind != "membership":
        raise PermissionDenied("Search Console requires a person membership.")
    return value


def source() -> SsaSource:
    return SsaSource(SourceConfig.configured(require_audit=False))


def _audit(ctx: TenantContext, action: str, target: UUID) -> None:
    record_audit(
        organization=Organization.objects.get(pk=ctx.organization_id),
        actor=User.objects.get(pk=ctx.actor_id),
        action=action,
        target_type="seo_gsc",
        target_id=target,
        metadata={},
    )


def erasure_check(organization_id: UUID) -> None:
    if GscWorkspaceState.all_objects.filter(
        organization_id=organization_id,
        cleanup_required=True,
    ).exists():
        raise ErasureBlocked("seo_gsc_disconnect_required: confirm SSA disconnect before erasure")


def _workspace(ctx: TenantContext, client: SsaSource) -> GscWorkspaceState:
    # The same organization lock serializes OAuth/disconnect against tenant erasure.
    Organization.objects.select_for_update().get(pk=ctx.organization_id)
    row, _ = GscWorkspaceState.all_objects.get_or_create(
        organization_id=ctx.organization_id,
        source_id=client.config.source_id,
    )
    return row


def _binding(ctx: TenantContext, site_id: UUID, client: SsaSource) -> SourceSiteBinding:
    row = SourceSiteBinding.all_objects.filter(
        organization_id=ctx.organization_id,
        site_id=site_id,
        source_id=client.config.source_id,
    ).first()
    if row is None or row.remote_binding_id is None:
        raise GscConflict(detail="Prepare this site's Search Console connection first.")
    return row


def prepare(site_id: UUID) -> dict[str, Any]:
    ctx, client = context(manage=True), source()
    target = read_site_audit_target(site_id=site_id)
    _workspace(ctx, client)
    binding, _ = SourceSiteBinding.all_objects.get_or_create(
        organization_id=ctx.organization_id,
        site_id=site_id,
        source_id=client.config.source_id,
        defaults={
            "external_project_id": str(site_id),
            "name": target["name"],
            "root_url": target["root_url"],
        },
    )
    if binding.root_url != target["root_url"]:
        raise GscConflict
    if not binding.remote_binding_id:
        data = client.provision(
            ctx.organization_id,
            external_project_id=binding.external_project_id,
            name=binding.name,
            root_url=binding.root_url,
        )
        expected = {
            "source_id": str(client.config.source_id),
            "product_id": client.config.product_id,
            "deployment_id": client.config.deployment_id,
            "external_tenant_id": str(ctx.organization_id),
            "external_project_id": binding.external_project_id,
            "root_url": binding.root_url,
        }
        if any(str(data.get(key)) != value for key, value in expected.items()):
            raise SourceError("gsc_binding_identity_mismatch")
        try:
            binding.remote_binding_id = UUID(data["binding_id"])
            binding.remote_project_id = UUID(data["project_id"])
            binding.remote_organization_id = UUID(data["organization_id"])
        except (ValueError, KeyError, TypeError) as error:
            raise SourceError("gsc_binding_malformed") from error
        binding.save(
            update_fields=["remote_binding_id", "remote_project_id", "remote_organization_id"]
        )
        _audit(ctx, "seo.gsc.prepared", binding.id)
    return properties(site_id)


def _properties(
    client: SsaSource, ctx: TenantContext, binding: SourceSiteBinding
) -> dict[str, Any]:
    data = client._request(
        "GET",
        PREFIX + "properties/",
        ctx.organization_id,
        params={"external_project_id": binding.external_project_id},
    )
    try:
        connected = data["connected"]
        if not isinstance(connected, bool) or not isinstance(data["properties"], list):
            raise ValueError
        connection_id = str(UUID(data["connection_id"])) if connected else None
        rows = [
            {
                "id": str(UUID(row["id"])),
                "site_url": str(row["site_url"]),
                "permission_level": str(row["permission_level"]),
            }
            for row in data["properties"]
        ]
        if len(rows) > 1000 or (not connected and rows):
            raise ValueError
        return {"connected": connected, "connection_id": connection_id, "properties": rows}
    except (ValueError, KeyError, TypeError) as error:
        raise SourceError("gsc_properties_malformed") from error


def properties(site_id: UUID) -> dict[str, Any]:
    ctx, client = context(manage=True), source()
    return _properties(client, ctx, _binding(ctx, site_id, client))


def connection_status(site_id: UUID) -> dict[str, Any]:
    ctx, client = context(cleanup=True), source()
    data = _properties(client, ctx, _binding(ctx, site_id, client))
    return {"connected": data["connected"], "connection_id": data["connection_id"]}


def sync_history(grant_id: UUID) -> dict[str, Any]:
    ctx, client = context(), source()
    grant = _grant(ctx, grant_id, client)
    rows = GscSyncIntent.all_objects.filter(
        organization_id=ctx.organization_id, grant=grant
    ).order_by("-id")[:50]
    return {
        "items": [
            {
                "client_reference": row.client_reference,
                "start_date": row.start_date,
                "end_date": row.end_date,
                "remote_id": row.remote_id,
            }
            for row in rows
        ]
    }


def _session(request: Any) -> tuple[UUID, str]:
    session = getattr(request, "identity_user_session", None)
    if session is None:
        session = getattr(getattr(request, "_request", None), "identity_user_session", None)
    if session is None or session.revoked_at is not None or session.expires_at <= timezone.now():
        raise PermissionDenied("A current managed browser session is required.")
    return session.id, session.session_key_hash


def authorize(
    request: Any, *, site_id: UUID, locale: str, connection_id: UUID | None
) -> dict[str, Any]:
    ctx, client = context(manage=True), source()
    session_id, session_hash = _session(request)
    redirect_uri()
    binding = _binding(ctx, site_id, client)
    target = read_site_audit_target(site_id=site_id)
    if target["root_url"] != binding.root_url:
        raise GscConflict
    workspace = _workspace(ctx, client)
    current = _properties(client, ctx, binding)
    if current["connection_id"] != (str(connection_id) if connection_id else None):
        raise GscConflict
    # Commit even on an unknown source response (the view catches transport errors).
    workspace.cleanup_required = True
    workspace.save(update_fields=["cleanup_required", "updated_at"])
    GscOAuthAttempt.all_objects.filter(
        organization_id=ctx.organization_id, consumed_at=None
    ).update(
        consumed_at=timezone.now(),
    )
    data = client._request(
        "POST",
        PREFIX + "authorize/",
        ctx.organization_id,
        {"external_project_id": binding.external_project_id, "actor_id": str(ctx.actor_id)},
    )
    state, url = str(data.get("state", "")), str(data.get("authorization_url", ""))
    authorization_url(url, state)
    expiry = _datetime(data.get("expires_at", ""))
    if expiry is None or timezone.is_naive(expiry) or expiry <= timezone.now():
        raise SourceError("gsc_authorization_malformed")
    attempt = GscOAuthAttempt.all_objects.create(
        organization_id=ctx.organization_id,
        binding=binding,
        actor_id=ctx.actor_id,
        session_id=session_id,
        session_hash=session_hash,
        state_hash=hashlib.sha256(state.encode()).hexdigest(),
        locale=locale,
        expires_at=min(expiry, timezone.now() + timedelta(minutes=15)),
    )
    _audit(ctx, "seo.gsc.oauth_started", attempt.id)
    return {"authorization_url": url, "expires_at": attempt.expires_at}


def callback(request: Any, *, state: str, code: str, denied: bool) -> str:
    ctx, client = context(manage=True), source()
    session_id, session_hash = _session(request)
    if not 16 <= len(state) <= 512 or len(code) > 4096:
        raise PermissionDenied("Invalid OAuth callback.")
    with transaction.atomic():
        attempt = (
            GscOAuthAttempt.all_objects.select_for_update()
            .select_related("binding")
            .filter(
                organization_id=ctx.organization_id,
                actor_id=ctx.actor_id,
                session_id=session_id,
                session_hash=session_hash,
                state_hash=hashlib.sha256(state.encode()).hexdigest(),
                consumed_at=None,
                expires_at__gt=timezone.now(),
                binding__source_id=client.config.source_id,
            )
            .first()
        )
        if attempt is None:
            raise PermissionDenied(
                "OAuth state is expired, consumed or belongs to another session."
            )
        attempt.consumed_at = timezone.now()
        attempt.save(update_fields=["consumed_at"])
    if denied or not code:
        return attempt.locale + ":denied"
    try:
        result = client._request(
            "POST",
            PREFIX + "callback/",
            ctx.organization_id,
            {
                "external_project_id": attempt.binding.external_project_id,
                "actor_id": str(ctx.actor_id),
                "state": state,
                "code": code,
            },
        )
        if result.get("connected") is not True or not isinstance(result.get("properties"), list):
            raise SourceError("gsc_callback_malformed")
        try:
            UUID(str(result.get("connection_id")))
        except ValueError as error:
            raise SourceError("gsc_callback_malformed") from error
    except SourceError:
        return attempt.locale + ":failed"
    _audit(ctx, "seo.gsc.connected", attempt.id)
    return attempt.locale + ":connected"


def _grant(ctx: TenantContext, grant_id: UUID, client: SsaSource) -> GscGrantIntent:
    value = (
        GscGrantIntent.all_objects.select_related("binding")
        .filter(
            organization_id=ctx.organization_id,
            id=grant_id,
            binding__source_id=client.config.source_id,
        )
        .first()
    )
    if value is None:
        raise NotFound()
    if value.remote_id is None:
        raise GscConflict(detail="Grant outcome is unknown; retry the original grant request.")
    return value


def _grant_data(grant: GscGrantIntent, data: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "id": str(grant.remote_id),
        "binding_id": str(grant.binding.remote_binding_id),
        "external_project_id": grant.binding.external_project_id,
        "actor_id": str(grant.actor_id),
    }
    if (
        any(str(data.get(key)) != value for key, value in expected.items())
        or data.get("scopes") != ["read", "sync"]
        or not isinstance(data.get("connected"), bool)
        or (
            data.get("property_id") is not None
            and str(data["property_id"]) != str(grant.property_id)
        )
    ):
        raise SourceError("gsc_grant_identity_mismatch")
    expires = _datetime(data.get("expires_at", ""))
    if expires != grant.expires_at:
        raise SourceError("gsc_grant_identity_mismatch")
    result = {
        key: data.get(key)
        for key in (
            "property_id",
            "site_url",
            "scopes",
            "expires_at",
            "revoked_at",
            "connected",
        )
    }
    result.update(id=str(grant.id), site_id=str(grant.binding.site_id), latest_sync=None)
    if data.get("connected") and data.get("latest_sync"):
        result["latest_sync"] = _sync_data(data["latest_sync"])
    return result


def _live_grant(
    ctx: TenantContext, client: SsaSource, grant: GscGrantIntent, *, require_active: bool = False
) -> dict[str, Any]:
    data = _grant_data(
        grant, client._request("GET", PREFIX + f"grants/{grant.remote_id}/", ctx.organization_id)
    )
    if require_active and (
        not data["connected"] or data["revoked_at"] or grant.expires_at <= timezone.now()
    ):
        raise PermissionDenied("Search Console grant is disconnected, expired or revoked.")
    return data


def create_grant(
    *, site_id: UUID, property_id: UUID, expires_at: datetime, idempotency_key: str
) -> dict[str, Any]:
    ctx, client = context(manage=True), source()
    binding = _binding(ctx, site_id, client)
    workspace = _workspace(ctx, client)
    digest = canonical_hash({
        "site_id": str(site_id),
        "property_id": str(property_id),
        "expires_at": expires_at.isoformat(),
        "actor": str(ctx.actor_id),
    })
    grant, _ = GscGrantIntent.all_objects.get_or_create(
        organization_id=ctx.organization_id,
        idempotency_key=idempotency_key,
        defaults={
            "binding": binding,
            "actor_id": ctx.actor_id,
            "property_id": property_id,
            "expires_at": expires_at,
            "request_hash": digest,
        },
    )
    if grant.request_hash != digest:
        raise GscConflict
    if grant.remote_id:
        return _live_grant(ctx, client, grant)
    workspace.cleanup_required = True
    workspace.save(update_fields=["cleanup_required", "updated_at"])
    data = client._request(
        "POST",
        PREFIX + "grants/",
        ctx.organization_id,
        {
            "external_project_id": binding.external_project_id,
            "actor_id": str(ctx.actor_id),
            "property_id": str(property_id),
            "scopes": ["read", "sync"],
            "expires_at": expires_at.isoformat(),
        },
        idempotency_key=str(grant.id),
    )
    try:
        grant.remote_id = UUID(data["id"])
    except (KeyError, TypeError, ValueError) as error:
        raise SourceError("gsc_grant_malformed") from error
    result = _grant_data(grant, data)
    grant.save(update_fields=["remote_id"])
    _audit(ctx, "seo.gsc.granted", grant.id)
    return result


def list_grants(site_id: UUID, cursor: UUID | None = None) -> dict[str, Any]:
    ctx, client = context(), source()
    query = GscGrantIntent.all_objects.filter(
        organization_id=ctx.organization_id,
        binding__site_id=site_id,
        binding__source_id=client.config.source_id,
    ).order_by("-id")
    if cursor:
        query = query.filter(id__lt=cursor)
    rows = list(query[:51])
    return {
        "items": [
            {
                "id": row.id,
                "property_id": row.property_id,
                "expires_at": row.expires_at,
                "created_at": row.created_at,
                "outcome_known": row.remote_id is not None,
            }
            for row in rows[:50]
        ],
        "next_cursor": rows[49].id if len(rows) > 50 else None,
    }


def read_grant(grant_id: UUID) -> dict[str, Any]:
    ctx, client = context(), source()
    return _live_grant(ctx, client, _grant(ctx, grant_id, client))


def retry_grant(grant_id: UUID) -> dict[str, Any]:
    ctx, client = context(manage=True), source()
    grant = (
        GscGrantIntent.all_objects.select_related("binding")
        .filter(
            organization_id=ctx.organization_id,
            id=grant_id,
            actor_id=ctx.actor_id,
            binding__source_id=client.config.source_id,
        )
        .first()
    )
    if grant is None:
        raise NotFound()
    return create_grant(
        site_id=grant.binding.site_id,
        property_id=grant.property_id,
        expires_at=grant.expires_at,
        idempotency_key=grant.idempotency_key,
    )


def _sync_data(data: dict[str, Any]) -> dict[str, Any]:
    try:
        if not isinstance(data, dict):
            raise ValueError
        UUID(str(data["client_reference"]))
        if data.get("id") is not None:
            UUID(str(data["id"]))
        if (
            data.get("status")
            not in {
                "created",
                "dispatching",
                "queued",
                "running",
                "completed",
                "partial",
                "failed",
                "revoked",
            }
            or type(data.get("rows_received")) is not int
            or data["rows_received"] < 0
            or not isinstance(data.get("is_truncated"), bool)
        ):
            raise ValueError
    except (ValueError, KeyError, TypeError) as error:
        raise SourceError("gsc_sync_malformed") from error
    return {
        key: data.get(key)
        for key in ("id", "client_reference", "status", "rows_received", "is_truncated")
    }


def sync(
    *, grant_id: UUID, client_reference: UUID, start_date: date, end_date: date
) -> dict[str, Any]:
    ctx, client = context(manage=True), source()
    grant = _grant(ctx, grant_id, client)
    _live_grant(ctx, client, grant, require_active=True)
    _workspace(ctx, client)
    row, _ = GscSyncIntent.all_objects.get_or_create(
        organization_id=ctx.organization_id,
        client_reference=client_reference,
        defaults={
            "grant": grant,
            "actor_id": ctx.actor_id,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    if (
        row.grant_id != grant.id
        or row.actor_id != ctx.actor_id
        or row.start_date != start_date
        or row.end_date != end_date
    ):
        raise GscConflict
    data = client._request(
        "POST",
        PREFIX + f"grants/{grant.remote_id}/sync/",
        ctx.organization_id,
        {
            "client_reference": str(client_reference),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "inspect_urls": False,
        },
    )
    if str(data.get("client_reference")) != str(client_reference):
        raise SourceError("gsc_sync_identity_mismatch")
    try:
        remote_id = UUID(data["id"]) if data.get("id") else None
    except (TypeError, ValueError) as error:
        raise SourceError("gsc_sync_malformed") from error
    if row.remote_id and remote_id and row.remote_id != remote_id:
        raise SourceError("gsc_sync_identity_mismatch")
    result = _sync_data(data)
    if remote_id is not None:
        row.remote_id = remote_id
        row.save(update_fields=["remote_id"])
    _audit(ctx, "seo.gsc.sync_requested", row.id)
    return result


def metrics(*, grant_id: UUID, sync_run_id: UUID, page: int, page_size: int) -> dict[str, Any]:
    ctx, client = context(), source()
    grant = _grant(ctx, grant_id, client)
    _live_grant(ctx, client, grant, require_active=True)
    if not GscSyncIntent.all_objects.filter(
        organization_id=ctx.organization_id, grant=grant, remote_id=sync_run_id
    ).exists():
        raise NotFound()
    data = client._request(
        "GET",
        PREFIX + f"grants/{grant.remote_id}/metrics/",
        ctx.organization_id,
        params={"sync_run_id": str(sync_run_id), "page": page, "page_size": page_size},
    )
    rows = data.get("results")
    if (
        not isinstance(rows, list)
        or len(rows) > page_size
        or not isinstance(data.get("count"), int)
    ):
        raise SourceError("gsc_metrics_malformed")
    if any(not isinstance(row, dict) for row in rows):
        raise SourceError("gsc_metrics_malformed")
    return {
        "count": data["count"],
        "next_page": page + 1 if data.get("next") else None,
        "results": [{key: row.get(key) for key in METRIC_FIELDS} for row in rows],
    }


def revoke(grant_id: UUID) -> dict[str, Any]:
    ctx, client = context(manage=True, cleanup=True), source()
    grant = _grant(ctx, grant_id, client)
    data = client._request(
        "POST", PREFIX + f"grants/{grant.remote_id}/revoke/", ctx.organization_id, {}
    )
    result = _grant_data(grant, data)
    _audit(ctx, "seo.gsc.revoked", grant.id)
    return result


def disconnect(*, site_id: UUID, connection_id: UUID | None) -> dict[str, Any]:
    ctx, client = context(manage=True, cleanup=True), source()
    binding = _binding(ctx, site_id, client)
    workspace = _workspace(ctx, client)
    data = client._request(
        "POST",
        PREFIX + "disconnect/",
        ctx.organization_id,
        {
            "external_project_id": binding.external_project_id,
            "actor_id": str(ctx.actor_id),
            "connection_id": str(connection_id) if connection_id else None,
        },
    )
    if not isinstance(data.get("disconnected"), bool) or str(data.get("external_tenant_id")) != str(
        ctx.organization_id
    ):
        raise SourceError("gsc_disconnect_unconfirmed")
    if not data["disconnected"]:
        if _properties(client, ctx, binding)["connected"]:
            raise SourceError("gsc_disconnect_unconfirmed")
        if connection_id is not None:
            return {"disconnected": False}
    workspace.cleanup_required = False
    workspace.save(update_fields=["cleanup_required", "updated_at"])
    GscOAuthAttempt.all_objects.filter(
        organization_id=ctx.organization_id, consumed_at=None
    ).update(consumed_at=timezone.now())
    _audit(ctx, "seo.gsc.disconnected", workspace.id)
    return {"disconnected": True}
