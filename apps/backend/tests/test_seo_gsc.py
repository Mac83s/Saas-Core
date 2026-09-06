from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid4

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from psycopg import sql

from saas_core.modules.core.identity.models import UserSession
from saas_core.modules.core.organizations.erasure import ErasureBlocked, erase_organization
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.seo.gsc.models import (
    GscGrantIntent,
    GscOAuthAttempt,
    GscSyncIntent,
    GscWorkspaceState,
)
from saas_core.modules.shared.seo.models import SourceSiteBinding
from saas_core.modules.shared.seo.source import SourceError, SsaSource
from saas_core.modules.shared.sites.models import Site
from test_seo_audits import seo  # noqa: F401
from test_sites_api import csrf_value, sites_client

pytestmark = pytest.mark.django_db
BASE = "/api/v1/seo/gsc/"


class FakeGsc:
    def __init__(self, fixture: Any, settings: Any):
        self.org, self.site, self.user = fixture[1], fixture[3], fixture[2]
        self.settings = settings
        self.connection: str | None = None
        self.property = str(uuid4())
        self.binding, self.project, self.remote_org = str(uuid4()), str(uuid4()), str(uuid4())
        self.calls: list[tuple[str, str]] = []
        self.state = "synthetic-oauth-state-" + uuid4().hex
        self.grants: dict[str, Any] = {}
        self.fail = ""
        self.grant_calls = 0
        self.sync_calls = 0
        self.sync_id = str(uuid4())
        self.revoked = False
        self.mismatch = False

    def request(
        self,
        method: str,
        path: str,
        tenant_id: UUID,
        payload: Any = None,
        params: Any = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        assert tenant_id == self.org.id
        self.calls.append((method, path))
        if self.fail and self.fail in path:
            raise SourceError("ssa_transport_unknown")
        if path == "/integration/projects/":
            return {
                "source_id": self.settings.SEO_SSA_SOURCE_ID,
                "product_id": "saas-core",
                "deployment_id": "test",
                "external_tenant_id": str(self.org.id),
                "external_project_id": str(self.site.id),
                "root_url": "https://owned.example.test/",
                "binding_id": self.binding,
                "project_id": self.project,
                "organization_id": self.remote_org,
            }
        if path.endswith("properties/"):
            return {
                "connected": self.connection is not None,
                "connection_id": self.connection,
                "properties": [
                    {
                        "id": self.property,
                        "site_url": "sc-domain:owned.example.test",
                        "permission_level": "siteOwner",
                    }
                ]
                if self.connection
                else [],
            }
        if path.endswith("authorize/"):
            query = urlencode({
                "state": self.state,
                "redirect_uri": self.settings.SEO_GSC_REDIRECT_URI,
            })
            return {
                "state": self.state,
                "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + query,
                "expires_at": (timezone.now() + timedelta(minutes=15)).isoformat(),
            }
        if path.endswith("callback/"):
            assert payload["actor_id"] == str(self.user.id)
            self.connection = str(uuid4())
            return {"connected": True, "connection_id": self.connection, "properties": []}
        if path.endswith("disconnect/"):
            if self.connection and payload["connection_id"] != self.connection:
                raise SourceError("ssa_http_409", retryable=False)
            removed = self.connection is not None
            self.connection = None
            self.revoked = True
            return {"disconnected": removed, "external_tenant_id": str(self.org.id)}
        if path == "/integration/gsc/grants/":
            self.grant_calls += 1
            if idempotency_key not in self.grants:
                self.grants[idempotency_key] = {
                    "id": str(uuid4()),
                    "binding_id": self.binding,
                    "external_project_id": str(self.site.id),
                    "actor_id": str(self.user.id),
                    "property_id": self.property,
                    "site_url": "sc-domain:owned.example.test",
                    "scopes": ["read", "sync"],
                    "expires_at": payload["expires_at"],
                    "revoked_at": None,
                    "connected": True,
                    "latest_sync": None,
                }
            return self.grants[idempotency_key]
        if path.endswith("metrics/"):
            return {
                "count": 1,
                "next": None,
                "results": [
                    {
                        "dataset": "daily",
                        "date": "2026-09-01",
                        "query": "private query",
                        "page": "https://owned.example.test/",
                        "country": "",
                        "device": "",
                        "search_appearance": "",
                        "clicks": 3,
                        "impressions": 9,
                        "ctr": 0.3,
                        "position": 2,
                        "refresh_token": "must-be-omitted",
                    }
                ],
            }
        if path.endswith("sync/"):
            self.sync_calls += 1
            return {
                "id": self.sync_id,
                "client_reference": payload["client_reference"],
                "status": "completed",
                "rows_received": 1,
                "is_truncated": False,
            }
        if "/grants/" in path:
            row = dict(next(iter(self.grants.values())))
            if path.endswith("revoke/"):
                self.revoked = True
            if self.revoked:
                row.update(connected=False, revoked_at=timezone.now().isoformat())
            if self.mismatch:
                row["binding_id"] = str(uuid4())
            return row
        raise AssertionError(path)


@pytest.fixture
def gsc(seo: Any, settings: Any, monkeypatch: Any) -> Any:  # noqa: F811
    settings.SEO_GSC_REDIRECT_URI = "https://core.example.test/api/v1/seo/gsc/callback/"
    snapshot = EntitlementSnapshot.all_objects.get(organization=seo[1])
    snapshot.features["seo.gsc.enabled"] = True
    snapshot.save()
    fake = FakeGsc(seo, settings)
    monkeypatch.setattr(
        SsaSource, "_request", lambda _self, *args, **kwargs: fake.request(*args, **kwargs)
    )
    return seo, fake


def post(gsc: Any, path: str, data: dict[str, Any]) -> Any:
    client = gsc[0][0]
    return client.post(BASE + path, data, format="json", HTTP_X_CSRFTOKEN=csrf_value(client))


def prepared(gsc: Any) -> None:
    response = post(gsc, "prepare/", {"site_id": str(gsc[0][3].id)})
    assert response.status_code == 200, response.content


def started(gsc: Any) -> None:
    prepared(gsc)
    response = post(
        gsc, "authorize/", {"site_id": str(gsc[0][3].id), "locale": "en", "connection_id": None}
    )
    assert response.status_code == 200, response.content


def granted(gsc: Any) -> tuple[str, dict[str, Any]]:
    prepared(gsc)
    gsc[1].connection = str(uuid4())
    body = {
        "site_id": str(gsc[0][3].id),
        "property_id": gsc[1].property,
        "expires_at": (timezone.now() + timedelta(days=30)).isoformat(),
        "idempotency_key": "grant-test-001",
    }
    response = post(gsc, "grants/", body)
    assert response.status_code == 200, response.content
    return response.json()["id"], body


def test_oauth_bound_to_session_and_one_use(gsc: Any) -> None:
    started(gsc)
    client, org, user, *_ = gsc[0]
    query = {"state": gsc[1].state, "code": "synthetic-code"}
    result = client.get(BASE + "callback/", query)
    assert (
        result.status_code == 302
        and result["Location"] == "/en/panel/seo/search-console?result=connected"
    )
    assert result["Cache-Control"] == "private, no-store"
    assert GscOAuthAttempt.all_objects.get().consumed_at is not None
    second = client.get(BASE + "callback/", query)
    assert "failed" in second["Location"]
    assert len([call for call in gsc[1].calls if call[1].endswith("callback/")]) == 1
    assert GscWorkspaceState.all_objects.get().cleanup_required
    with pytest.raises(ErasureBlocked, match="seo_gsc_disconnect_required"):
        erase_organization(organization=org, requested_by=user, reason="test")


@pytest.mark.parametrize("failure", ["session", "expired", "denied", "transport"])
def test_oauth_rejects_wrong_session_expiry_and_consumes_errors(gsc: Any, failure: str) -> None:
    started(gsc)
    row = GscOAuthAttempt.all_objects.get()
    if failure in {"session", "expired"}:
        # Immutable receipt: mutate current identity or time, never its recorded request.
        if failure == "session":
            UserSession.objects.filter(pk=row.session_id).update(revoked_at=timezone.now())
        else:
            from unittest.mock import patch

            with patch(
                "saas_core.modules.shared.seo.gsc.services.timezone.now",
                return_value=row.expires_at + timedelta(seconds=1),
            ):
                response = gsc[0][0].get(
                    BASE + "callback/", {"state": gsc[1].state, "code": "code"}
                )
            assert response.status_code in (302, 403)
            assert not any(path.endswith("callback/") for _, path in gsc[1].calls)
            return
    if failure == "transport":
        gsc[1].fail = "callback/"
    query = {"state": gsc[1].state, "code": "code"}
    if failure == "denied":
        query["error"] = "access_denied"
    response = gsc[0][0].get(BASE + "callback/", query)
    assert response.status_code in (302, 403)
    row.refresh_from_db()
    assert (row.consumed_at is not None) == (failure in {"denied", "transport"})


def test_grant_replay_conflict_live_revoke_and_private_metrics(gsc: Any) -> None:
    grant_id, body = granted(gsc)
    assert post(gsc, "grants/", body).status_code == 200
    assert gsc[1].grant_calls == 1 and GscGrantIntent.all_objects.count() == 1
    assert post(gsc, "grants/", {**body, "property_id": str(uuid4())}).status_code == 409
    sync_body = {
        "client_reference": str(uuid4()),
        "start_date": "2026-09-01",
        "end_date": "2026-09-02",
    }
    sync_response = post(gsc, f"grants/{grant_id}/sync/", sync_body)
    assert sync_response.status_code == 200, sync_response.content
    response = gsc[0][0].get(BASE + f"grants/{grant_id}/metrics/", {"sync_run_id": gsc[1].sync_id})
    assert response.status_code == 200, response.content
    assert "refresh_token" not in str(response.json())
    assert response["Cache-Control"] == "private, no-store"
    assert post(gsc, f"grants/{grant_id}/revoke/", {}).status_code == 200
    assert gsc[0][0].get(BASE + f"grants/{grant_id}/").json()["connected"] is False
    calls = gsc[1].sync_calls
    assert post(gsc, f"grants/{grant_id}/sync/", sync_body).status_code == 403
    assert gsc[1].sync_calls == calls
    assert (
        gsc[0][0]
        .get(BASE + f"grants/{grant_id}/metrics/", {"sync_run_id": gsc[1].sync_id})
        .status_code
        == 403
    )


def test_identity_mismatch_stops_metrics_before_read(gsc: Any) -> None:
    grant_id, _ = granted(gsc)
    gsc[1].mismatch = True
    response = gsc[0][0].get(BASE + f"grants/{grant_id}/metrics/", {"sync_run_id": str(uuid4())})
    assert response.status_code == 503
    assert not any(path.endswith("metrics/") for _, path in gsc[1].calls)


def test_unknown_oauth_keeps_cleanup_fence_and_disconnect_is_guarded(gsc: Any) -> None:
    prepared(gsc)
    gsc[1].fail = "authorize/"
    response = post(gsc, "authorize/", {"site_id": str(gsc[0][3].id), "connection_id": None})
    assert response.status_code == 503
    assert GscWorkspaceState.all_objects.get().cleanup_required
    gsc[1].fail = ""
    gsc[1].connection = str(uuid4())
    body = {
        "site_id": str(gsc[0][3].id),
        "connection_id": str(uuid4()),
        "confirm_workspace_disconnect": True,
    }
    assert post(gsc, "disconnect/", body).status_code == 409
    assert GscWorkspaceState.all_objects.get().cleanup_required
    assert post(gsc, "disconnect/", {**body, "connection_id": gsc[1].connection}).status_code == 200
    assert not GscWorkspaceState.all_objects.get().cleanup_required


def test_no_feature_or_csrf_does_not_contact_source(gsc: Any) -> None:
    client, org, *_ = gsc[0]
    snapshot = EntitlementSnapshot.all_objects.get(organization=org)
    snapshot.features["seo.gsc.enabled"] = False
    snapshot.save()
    assert post(gsc, "prepare/", {"site_id": str(gsc[0][3].id)}).status_code == 403
    assert not gsc[1].calls
    assert (
        client.post(BASE + "prepare/", {"site_id": str(gsc[0][3].id)}, format="json").status_code
        == 403
    )


def test_tenant_is_set_before_gsc_tables(gsc: Any) -> None:
    with CaptureQueriesContext(connection) as queries:
        prepared(gsc)
    statements = [row["sql"] for row in queries]
    first_set = next(
        i for i, statement in enumerate(statements) if "SET LOCAL app.organization_id" in statement
    )
    first_gsc = next(
        i for i, statement in enumerate(statements) if '"seo_gscworkspacestate"' in statement
    )
    assert first_set < first_gsc


def test_four_gsc_tables_nonowner_role(gsc: Any) -> None:
    started(gsc)
    grant_id, _ = granted(gsc)
    assert (
        post(
            gsc,
            f"grants/{grant_id}/sync/",
            {
                "client_reference": str(uuid4()),
                "start_date": "2026-09-01",
                "end_date": "2026-09-02",
            },
        ).status_code
        == 200
    )
    _, other, other_user = sites_client(slug="gsc-other", role_key="owner")
    other_site = Site.all_objects.create(
        organization=other, name="Other", slug="other", created_by=other_user
    )
    binding = SourceSiteBinding.all_objects.create(
        organization=other,
        site=other_site,
        source_id=uuid4(),
        external_project_id=str(other_site.id),
        name="Other",
        root_url="https://other.example.test/",
    )
    GscWorkspaceState.all_objects.create(organization=other, source_id=binding.source_id)
    GscOAuthAttempt.all_objects.create(
        organization=other,
        binding=binding,
        actor=other_user,
        session_id=uuid4(),
        session_hash="a" * 64,
        state_hash="b" * 64,
        expires_at=timezone.now() + timedelta(minutes=1),
    )
    other_grant = GscGrantIntent.all_objects.create(
        organization=other,
        binding=binding,
        actor=other_user,
        property_id=uuid4(),
        expires_at=timezone.now() + timedelta(days=1),
        idempotency_key="other-key",
        request_hash="c" * 64,
    )
    GscSyncIntent.all_objects.create(
        organization=other,
        grant=other_grant,
        actor=other_user,
        client_reference=uuid4(),
        start_date="2026-09-01",
        end_date="2026-09-02",
    )
    role = sql.Identifier("gsc_probe_" + uuid4().hex)
    tables = [
        "seo_gscworkspacestate",
        "seo_gscoauthattempt",
        "seo_gscgrantintent",
        "seo_gscsyncintent",
    ]
    names = sql.SQL(", ").join(map(sql.Identifier, tables))
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(role))
        try:
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            cursor.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(names, role))
            with transaction.atomic():
                cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(role))
                counts = []
                for tenant in [None, gsc[0][1].id, other.id]:
                    cursor.execute(
                        "SELECT set_config('app.organization_id', %s, true)",
                        [str(tenant) if tenant else ""],
                    )
                    counts.append([])
                    for table in tables:
                        cursor.execute(
                            sql.SQL("SELECT organization_id FROM {}").format(sql.Identifier(table))
                        )
                        rows = cursor.fetchall()
                        assert rows == ([(tenant,)] if tenant is not None else [])
                        counts[-1].append(len(rows))
                cursor.execute("RESET ROLE")
                print("GSC nonowner no tenant/A/B:", counts)

        finally:
            cursor.execute("RESET ROLE")
            cursor.execute(sql.SQL("REVOKE SELECT ON {} FROM {}").format(names, role))
            cursor.execute(sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(role))
            cursor.execute(sql.SQL("DROP ROLE {}").format(role))


@pytest.mark.parametrize("corrupt", ["date", "url"])
def test_malformed_remote_authorize_keeps_cleanup_marker(
    gsc: Any, monkeypatch: Any, corrupt: str
) -> None:
    prepared(gsc)
    original = gsc[1].request

    def bad(method: str, path: str, *args: Any, **kwargs: Any) -> Any:
        result = original(method, path, *args, **kwargs)
        if path.endswith("authorize/"):
            result["expires_at" if corrupt == "date" else "authorization_url"] = (
                "2026-99-99T12:00:00Z" if corrupt == "date" else "https://[invalid"
            )
        return result

    monkeypatch.setattr(gsc[1], "request", bad)
    response = post(gsc, "authorize/", {"site_id": str(gsc[0][3].id), "connection_id": None})
    assert response.status_code in (409, 503), response.content
    assert GscWorkspaceState.all_objects.get().cleanup_required
    assert GscOAuthAttempt.all_objects.count() == 0


def test_gsc_config_independent_of_audit_and_cleanup_after_feature_removed(
    gsc: Any, settings: Any
) -> None:
    settings.SEO_SSA_CALLBACK_SECRET = ""
    settings.SEO_AUDIT_CREDIT_OPERATION = ""
    grant_id, _ = granted(gsc)
    snapshot = EntitlementSnapshot.all_objects.get(organization=gsc[0][1])
    snapshot.features["seo.gsc.enabled"] = False
    snapshot.save()
    client = gsc[0][0]
    assert client.get(BASE + "properties/", {"site_id": str(gsc[0][3].id)}).status_code == 403
    status = client.get(BASE + "connection/", {"site_id": str(gsc[0][3].id)})
    assert status.status_code == 200 and "properties" not in status.json()
    assert post(gsc, f"grants/{grant_id}/revoke/", {}).status_code == 200
    assert (
        post(
            gsc,
            "disconnect/",
            {
                "site_id": str(gsc[0][3].id),
                "connection_id": status.json()["connection_id"],
                "confirm_workspace_disconnect": True,
            },
        ).status_code
        == 200
    )
    assert not GscWorkspaceState.all_objects.get().cleanup_required


def test_callback_query_is_redacted_from_django_access_log() -> None:
    import logging

    from saas_core.observability.logging import JsonFormatter

    record = logging.LogRecord(
        "django.server",
        logging.INFO,
        "",
        0,
        '"GET /api/v1/seo/gsc/callback/?code=private&state=private HTTP/1.1" 302',
        (),
        None,
    )
    text = JsonFormatter().format(record)
    assert "code=private" not in text and "state=private" not in text and "[redacted]" in text
