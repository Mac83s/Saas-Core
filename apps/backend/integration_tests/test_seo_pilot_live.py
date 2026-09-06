"""Opt-in three-process API gate; uses synthetic data and no provider calls.

Run with Core pytest settings and SCR_PILOT_REPO/PYTHON and SSA_PILOT_REPO/PYTHON.
The two peers get new SQLite files; Core uses pytest's PostgreSQL test database.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from saas_core.modules.shared.notifications.models import ApiKey  # noqa: E402
from saas_core.modules.shared.sites.models import (  # noqa: E402
    ContentAutomationGrant,
    Domain,
    PageTranslation,
    PageVersion,
    Publication,
)
from test_sites_api import (  # noqa: E402
    create_page,
    create_site,
    csrf_value,
    save_draft,
    sites_client,
)
from test_sites_operations import _api_key_client  # noqa: E402

pytestmark = pytest.mark.django_db(transaction=True)
HELPER = Path(__file__).with_name("seo_pilot_peer.py")


@pytest.fixture(scope="session")
def migration_seed(django_db_setup, django_db_blocker):
    from django.db import connection

    with django_db_blocker.unblock():
        rows = json.loads(connection.creation.serialize_db_to_string())
        # Django post_migrate recreates these with fresh integer IDs after flush.
        return json.dumps([
            row
            for row in rows
            if row["model"]
            not in {
                "contenttypes.contenttype",
                "auth.permission",
            }
        ])


@pytest.fixture(autouse=True)
def restore_migration_seed(migration_seed, transactional_db):
    from django.db import connection

    from saas_core.modules.core.organizations.models import Role

    # Transaction tests flush seed rows too. Django's serialized rollback first
    # UPDATEs existing immutable roles; restore only into the flushed database.
    if not Role.objects.filter(organization__isnull=True).exists():
        connection.creation.deserialize_db_from_string(migration_seed)


def _request(url: str, *, body: dict | None = None, headers: dict | None = None) -> SimpleNamespace:
    request = Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        response = urlopen(request, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        text = response.read().decode()
        return SimpleNamespace(
            status_code=response.status, text=text, json=lambda: json.loads(text)
        )


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _peer(tmp_path: Path, kind: str) -> tuple[str, str, dict[str, str]]:
    repo = os.environ.get(f"{kind}_PILOT_REPO")
    python = os.environ.get(f"{kind}_PILOT_PYTHON")
    if not repo or not python:
        pytest.skip("Explicit peer repositories and interpreters are required.")
    module = f"pilot_{kind.lower()}_settings"
    parent = "config.test_settings" if kind == "SSA" else "seocontentrank.config.test_settings"
    settings_file = tmp_path / f"{module}.py"
    database = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(tmp_path / (kind + ".sqlite3")),
        }
    }
    settings_file.write_text(
        f"from {parent} import *\n"
        f"DATABASES = {database!r}\n"
        "ALLOWED_HOSTS = ['*']\n"
        "DEBUG = False\n"
        "SECURE_SSL_REDIRECT = False\n",
        encoding="utf-8",
    )
    if kind == "SSA":
        with settings_file.open("a", encoding="utf-8") as handle:
            handle.write(
                "MODULE_RUN_CALLBACK_RECIPIENTS = {'pilot': "
                "{'url': 'http://127.0.0.1:9/callback', 'secret': 'synthetic-only'}}\n"
            )
    env = os.environ.copy()
    source = repo if kind == "SSA" else str(Path(repo) / "apps/backend/src")
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), source])
    env["DJANGO_SETTINGS_MODULE"] = module
    if kind == "SCR":
        from cryptography.fernet import Fernet

        env["SEOCONTENTRANK_CREDENTIAL_KEY"] = Fernet.generate_key().decode()
    return python, repo, env


def _run(peer: tuple, action: str, context: Path) -> None:
    python, repo, env = peer
    result = subprocess.run(
        [python, str(HELPER), action, str(context)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr[-6000:]


def _server(peer: tuple, port: int, context: Path, log: object) -> subprocess.Popen:
    python, repo, env = peer
    process = subprocess.Popen(
        [python, str(HELPER), "serve", str(context), str(port)],
        cwd=repo,
        env=env,
        stdout=log,
        stderr=log,
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        assert process.poll() is None, "Peer did not start; inspect the private test log."
        try:
            _request(f"http://127.0.0.1:{port}/api/v1/")
            return process
        except (URLError, TimeoutError):
            time.sleep(0.1)
    process.terminate()
    process.wait(timeout=5)
    raise AssertionError("Peer startup timed out.")


def test_core_delegates_google_consent_and_revocation_over_http(live_server, tmp_path, settings):
    from datetime import timedelta
    from urllib.parse import parse_qs, urlsplit

    from django.utils import timezone

    from saas_core.modules.core.organizations.erasure import ErasureBlocked, erase_organization
    from saas_core.modules.shared.billing.models import EntitlementSnapshot
    from saas_core.modules.shared.seo.gsc.models import GscWorkspaceState

    settings.CONFIGURED_ALLOWED_HOSTS = ("testserver", "localhost", "127.0.0.1")
    ssa = _peer(tmp_path, "SSA")
    port = _port()
    context_file = tmp_path / "private-context.json"
    context_file.write_text(json.dumps({"synthetic_google": True}), encoding="utf-8")
    _run(ssa, "seed_order_source", context_file)
    data = json.loads(context_file.read_text(encoding="utf-8"))
    redirect = live_server.url + "/api/v1/seo/gsc/callback/"
    with (tmp_path / "pilot_ssa_settings.py").open("a", encoding="utf-8") as handle:
        handle.write(
            "\nGOOGLE_OAUTH_CLIENT_ID = 'synthetic.apps.googleusercontent.com'\n"
            "GOOGLE_OAUTH_CLIENT_SECRET = 'synthetic-client-secret'\n"
            "GOOGLE_TOKEN_ENCRYPTION_KEY = 'synthetic-encryption-only'\n"
            f"GOOGLE_OAUTH_REDIRECT_URI = {redirect!r}\n"
            f"SSA_INTEGRATION_GSC_REDIRECTS = {{{data['source_id']!r}: {redirect!r}}}\n"
        )
    settings.SEO_SSA_BASE_URL = f"http://127.0.0.1:{port}/api/v1"
    settings.SEO_SSA_SOURCE_ID = data["source_id"]
    settings.SEO_SSA_PRODUCT_ID = "saas-core"
    settings.SEO_SSA_DEPLOYMENT_ID = "local-pilot"
    settings.SEO_SSA_SERVICE_KEY = data["source_key"]
    settings.SEO_GSC_REDIRECT_URI = redirect
    person, organization, owner = sites_client(slug="live-google", role_key="owner")
    EntitlementSnapshot.all_objects.filter(organization=organization).update(
        features={"sites.enabled": True, "seo.gsc.enabled": True}
    )
    site = create_site(person).data["id"]
    Domain.all_objects.filter(site_id=site).update(is_canonical=False)
    Domain.all_objects.create(
        organization=organization,
        site_id=site,
        hostname="pilot.example.test",
        kind="custom",
        status="verified",
        is_canonical=True,
        created_by=owner,
    )
    api = "/api/v1/seo/gsc/"

    def post(path, body):
        return person.post(api + path, body, format="json", HTTP_X_CSRFTOKEN=csrf_value(person))

    with (tmp_path / "ssa.log").open("w") as log:
        process = _server(ssa, port, context_file, log)
        try:
            prepared = post("prepare/", {"site_id": str(site)})
            assert prepared.status_code == 200, prepared.content
            assert prepared.json()["connected"] is False
            authorized = post(
                "authorize/", {"site_id": str(site), "locale": "en", "connection_id": None}
            )
            assert authorized.status_code == 200, authorized.content
            state = parse_qs(urlsplit(authorized.json()["authorization_url"]).query)["state"][0]
            with pytest.raises(ErasureBlocked, match="disconnect_required"):
                erase_organization(organization=organization, requested_by=None, reason="Synthetic")
            callback = person.get(
                api + "callback/", {"state": state, "code": "synthetic-google-code"}
            )
            assert callback.status_code == 302
            assert "result=connected" in callback["Location"], callback["Location"]
            properties = person.get(api + "properties/", {"site_id": str(site)})
            assert properties.status_code == 200, properties.content
            assert properties.json()["connected"] is True
            assert "synthetic-access" not in properties.content.decode()
            assert "synthetic-refresh" not in properties.content.decode()
            assert (
                "result=failed"
                in person.get(api + "callback/", {"state": state, "code": "synthetic-google-code"})[
                    "Location"
                ]
            )
            grant = post(
                "grants/",
                {
                    "site_id": str(site),
                    "property_id": properties.json()["properties"][0]["id"],
                    "expires_at": (timezone.now() + timedelta(days=7)).isoformat(),
                    "idempotency_key": "live-google-grant",
                },
            )
            assert grant.status_code == 200, grant.content
            grant_id = grant.json()["id"]
            revoked = post(f"grants/{grant_id}/revoke/", {})
            assert revoked.status_code == 200, revoked.content
            assert revoked.json()["revoked_at"]
            disconnected = post(
                "disconnect/",
                {
                    "site_id": str(site),
                    "connection_id": properties.json()["connection_id"],
                    "confirm_workspace_disconnect": True,
                },
            )
            assert disconnected.status_code == 200, disconnected.content
            assert disconnected.json()["disconnected"] is True
            assert not GscWorkspaceState.all_objects.get(organization=organization).cleanup_required
            erase_organization(
                organization=organization, requested_by=None, reason="Synthetic teardown"
            )
        finally:
            process.terminate()
            process.wait(timeout=5)


def test_brief_to_core_draft_over_http_without_prior_audit(live_server, tmp_path, settings):
    from saas_core.modules.shared.notifications.models import ApiKeyCredentialRoute
    from saas_core.modules.shared.sites.models import BlueprintImportReceipt, ContentProposal, Page
    from test_content_proposal_review import accept, detail

    settings.CONFIGURED_ALLOWED_HOSTS = ("testserver", "localhost", "127.0.0.1")
    scr = _peer(tmp_path, "SCR")
    with (tmp_path / "pilot_scr_settings.py").open("a", encoding="utf-8") as handle:
        handle.write(
            "\nBLUEPRINT_MODELS = 'synthetic-only'\nBLUEPRINT_MAX_INPUT_CHARS = '20000'\n"
            "BLUEPRINT_MAX_OUTPUT_TOKENS = '2000'\nBLUEPRINT_MAX_PROVIDER_CALLS = '1'\n"
            "BLUEPRINT_WORKSPACE_DAILY_CALLS = '2'\nOPENROUTER_API_KEY = 'synthetic-never-sent'\n"
        )
    person, organization, owner = sites_client(slug="live-brief", role_key="owner")
    site = create_site(person).data["id"]
    _api_key_client(organization=organization, created_by=owner, marker="b")
    key = ApiKey.all_objects.get(organization=organization)
    key.scopes = ["content:read", "content:draft"]
    key.save(update_fields=["scopes"])
    ApiKeyCredentialRoute.objects.filter(api_key_id=key.id).update(scopes=key.scopes)
    ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=key.id,
        site_id=site,
        mode="draft_write",
        created_by=owner,
    )
    port = _port()
    context = tmp_path / "private-context.json"
    data = {
        "core_url": live_server.url,
        "core_key": "sc_live_" + "b" * 32,
        "scr_url": f"http://127.0.0.1:{port}",
        "site_id": str(site),
    }
    context.write_text(json.dumps(data), encoding="utf-8")
    _run(scr, "seed_scr_blueprint", context)
    data = json.loads(context.read_text(encoding="utf-8"))
    with (tmp_path / "scr.log").open("w") as log:
        process = _server(scr, port, context, log)
        try:
            headers = {"Authorization": f"Bearer {data['scr_key']}"}
            api = data["scr_url"] + "/api/v1/site-blueprints/"
            query = urlencode({"site_id": data["site_id"], "connection_id": data["connection_id"]})
            catalog = _request(api + "catalog/?" + query, headers=headers)
            assert catalog.status_code == 200, catalog.text
            created = _request(
                api,
                headers={**headers, "Idempotency-Key": "live-brief"},
                body={
                    "connection_id": data["connection_id"],
                    "site_id": data["site_id"],
                    "template_id": catalog.json()["templates"][0]["id"],
                    "locale": "pl",
                    "page_name": "Synthetic studio",
                    "page_key": "studio",
                    "brief": {
                        "business_name": "Synthetic studio",
                        "summary": "Test site only.",
                        "audience": "Synthetic customer",
                        "services": ["Test service"],
                    },
                },
            )
            assert created.status_code == 202, created.text
            data["generation_id"] = created.json()["id"]
            context.write_text(json.dumps(data), encoding="utf-8")
            _run(scr, "generate_scr_blueprint", context)
            item = api + data["generation_id"] + "/"
            approved = _request(
                item + "accept/",
                headers={**headers, "Idempotency-Key": "review-brief"},
                body={"reason": "Reviewed synthetic copy"},
            )
            assert approved.status_code == 200, approved.text
            delivered = _request(item + "deliver/", headers=headers, body={})
            assert delivered.status_code == 200, delivered.text
            assert delivered.json()["state"] == "accepted", delivered.text
            receipt = delivered.json()["receipt"]
            assert receipt["published"] is False
            assert Page.all_objects.count() == 1
            assert PageVersion.all_objects.count() == 1
            assert not Publication.all_objects.exists()
            assert BlueprintImportReceipt.all_objects.count() == 1
            proposal = ContentProposal.all_objects.get(pk=receipt["proposal_id"])
            assert (
                accept(person, proposal, detail(person, proposal)["review_token"]).status_code
                == 200
            )
            assert _request(item + "deliver/", headers=headers, body={}).json() == delivered.json()
            assert PageVersion.all_objects.count() == 1
            assert not Publication.all_objects.exists()
        finally:
            process.terminate()
            process.wait(timeout=5)


@pytest.mark.parametrize("mode", ["suggest_only", "draft_write"])
def test_existing_audit_to_retained_proposal_to_core_preview(
    live_server, tmp_path: Path, settings, mode
) -> None:
    settings.CONFIGURED_ALLOWED_HOSTS = ("testserver", "localhost", "127.0.0.1")
    ssa, scr = _peer(tmp_path, "SSA"), _peer(tmp_path, "SCR")
    person, organization, owner = sites_client(slug="live-pilot", role_key="owner")
    site = create_site(person).data["id"]
    page = create_page(person, site, key="about").data["id"]
    saved = save_draft(
        person, page, expected_version=0, idempotency_key="pilot-draft", heading="Pilot"
    )
    assert saved.status_code == 201, saved.content
    PageTranslation.all_objects.update_or_create(
        organization=organization,
        site_id=site,
        page_id=page,
        locale="pl",
        defaults={"slug": "about", "title": "Pilot", "description": ""},
    )
    Domain.all_objects.create(
        organization=organization,
        site_id=site,
        hostname="pilot.example.test",
        kind="custom",
        status="verified",
        created_by=owner,
        idempotency_key="pilot-domain",
        request_hash="a" * 64,
    )
    _api_key_client(organization=organization, created_by=owner, marker="z")
    key = ApiKey.all_objects.get(organization=organization)
    if mode == "draft_write":
        from saas_core.modules.shared.notifications.models import ApiKeyCredentialRoute
        from saas_core.modules.shared.sites.models import Page

        key.scopes = ["content:read", "content:draft"]
        key.save(update_fields=["scopes"])
        ApiKeyCredentialRoute.objects.filter(api_key_id=key.id).update(scopes=key.scopes)
        Page.all_objects.filter(pk=page).update(automation_policy="proposed")
    grant = ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=key.id,
        site_id=site,
        mode=mode,
        created_by=owner,
    )
    ssa_port, scr_port = _port(), _port()
    context = tmp_path / "private-context.json"
    data = {
        "mode": mode,
        "core_url": live_server.url,
        "core_key": "sc_live_" + "z" * 32,
        "ssa_url": f"http://127.0.0.1:{ssa_port}",
        "scr_url": f"http://127.0.0.1:{scr_port}",
        "site_id": str(site),
        "page_id": str(page),
        "page_url": "https://pilot.example.test/about/",
    }
    context.write_text(json.dumps(data), encoding="utf-8")
    _run(ssa, "seed_ssa", context)
    processes = []
    with (tmp_path / "ssa.log").open("w") as ssa_log, (tmp_path / "scr.log").open("w") as scr_log:
        try:
            processes.append(_server(ssa, ssa_port, context, ssa_log))
            _run(scr, "seed_scr", context)
            processes.append(_server(scr, scr_port, context, scr_log))
            data = json.loads(context.read_text(encoding="utf-8"))
            headers = {"Authorization": f"Bearer {data['scr_key']}"}
            created = _request(
                f"{data['scr_url']}/api/v1/proposals/",
                body=data["proposal_request"],
                headers={
                    **headers,
                    "Idempotency-Key": data["proposal_request"]["payload"]["idempotency_key"],
                },
            )
            assert created.status_code == 201, created.text
            data["proposal_id"] = created.json()["id"]
            context.write_text(json.dumps(data), encoding="utf-8")
            assert (
                _request(
                    f"{data['scr_url']}/api/v1/proposals/{data['proposal_id']}/", headers=headers
                ).status_code
                == 200
            )
            before = (PageVersion.all_objects.count(), Publication.all_objects.count())
            if mode == "suggest_only":
                _run(scr, "preview_scr", context)
                data = json.loads(context.read_text(encoding="utf-8"))
                report = data["report"]
                assert report["preview"]["accepted"] is True, report
                assert report["base_unchanged"] is True
                assert before == (PageVersion.all_objects.count(), Publication.all_objects.count())
                assert PageTranslation.all_objects.get(page_id=page, locale="pl").description == ""
                assert not report["apply_requested"] and not report["publish_requested"]
            else:
                accepted = _request(
                    f"{data['scr_url']}/api/v1/proposals/{data['proposal_id']}/accept/",
                    body={"reason": "Reviewed synthetic description"},
                    headers={**headers, "Idempotency-Key": "synthetic-review-001"},
                )
                assert accepted.status_code == 200, accepted.text
                delivered = _request(
                    f"{data['scr_url']}/api/v1/proposal-delivery/{data['proposal_id']}/deliver/",
                    body={"binding": data["binding"]},
                    headers=headers,
                )
                assert delivered.status_code == 200, delivered.text
                report = delivered.json()["report"]
                assert report["delivery"]["accepted"], report
                result = report["delivery"]["result"]
                assert result["published"] is False
                assert result["pending_commands"] == ["translation.update"]
                assert PageVersion.all_objects.count() == before[0] + 1
                assert Publication.all_objects.count() == before[1]
                assert PageTranslation.all_objects.get(page_id=page, locale="pl").description == ""
                core_headers = {
                    "Cookie": "; ".join(
                        f"{name}={cookie.value}" for name, cookie in person.cookies.items()
                    ),
                    "X-CSRFToken": csrf_value(person),
                    "Origin": live_server.url,
                }
                proposal_url = live_server.url + f"/api/v1/sites/proposals/{result['proposal_id']}/"
                review = _request(proposal_url, headers=core_headers)
                assert review.status_code == 200, review.text
                accepted_core = _request(
                    proposal_url + "accept/",
                    headers=core_headers,
                    body={"review_token": review.json()["review_token"]},
                )
                assert accepted_core.status_code == 200, accepted_core.text
                assert accepted_core.json()["published"] is False
                assert (
                    PageTranslation.all_objects.get(page_id=page, locale="pl").description
                    == data["proposal_request"]["payload"]["commands"][0]["value"]
                )
                replay = _request(
                    f"{data['scr_url']}/api/v1/proposal-delivery/{data['proposal_id']}/deliver/",
                    body={"binding": data["binding"]},
                    headers=headers,
                )
                assert replay.status_code == 200, replay.text
                assert replay.json()["report"]["operation_found"] is True
                assert PageVersion.all_objects.count() == before[0] + 1
                assert Publication.all_objects.count() == before[1]
                report["human_metadata_accepted_without_publication"] = True
            # Revocation is effective on the next real HTTP request.
            from django.utils import timezone

            grant.revoked_at = timezone.now()
            grant.save(update_fields=["revoked_at"])
            response = _request(
                f"{live_server.url}/api/v1/sites/content-base/?{urlencode(report['target'])}",
                headers={"Authorization": f"Bearer {data['core_key']}"},
            )
            assert response.status_code == 403, response.text
            report.update(
                synthetic=True,
                imported_findings=data["imported_findings"],
                imported_pages=data["imported_pages"],
                revoked_grant_status=403,
            )
            (tmp_path / "evidence.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        finally:
            for process in reversed(processes):
                process.terminate()
                process.wait(timeout=10)


@pytest.mark.parametrize(
    "outcome,credit_state", [("completed", "committed"), ("partial", "released")]
)
def test_core_orders_and_settles_ssa_audit_over_http(
    live_server, tmp_path, settings, outcome, credit_state
):
    from saas_core.modules.shared.billing.models import (
        CreditOperation,
        CreditReservation,
        EntitlementSnapshot,
    )
    from saas_core.modules.shared.seo.models import AuditCallbackReceipt, AuditOrder
    from saas_core.modules.shared.seo.worker import dispatch_audit
    from saas_core.modules.shared.sites.models import Site

    settings.CONFIGURED_ALLOWED_HOSTS = ("testserver", "localhost", "127.0.0.1")
    ssa = _peer(tmp_path, "SSA")
    port = _port()
    context = tmp_path / "private-context.json"
    context.write_text(json.dumps({"outcome": outcome}), encoding="utf-8")
    settings_path = tmp_path / "pilot_ssa_settings.py"
    with settings_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "MODULE_RUN_CALLBACK_RECIPIENTS = {'pilot': "
            f"{{'url': {live_server.url + '/api/v1/seo/ssa/callback/'!r}, "
            "'secret': 'synthetic-callback-key'}}\n"
        )
    _run(ssa, "seed_order_source", context)
    data = json.loads(context.read_text(encoding="utf-8"))
    settings.SEO_SSA_BASE_URL = f"http://127.0.0.1:{port}/api/v1"
    settings.SEO_SSA_SOURCE_ID = data["source_id"]
    settings.SEO_SSA_PRODUCT_ID = "saas-core"
    settings.SEO_SSA_DEPLOYMENT_ID = "local-pilot"
    settings.SEO_SSA_SERVICE_KEY = data["source_key"]
    settings.SEO_SSA_CALLBACK_SECRET = "synthetic-callback-key"
    settings.SEO_AUDIT_CREDIT_OPERATION = "seo.synthetic.audit"
    person, organization, user = sites_client(slug="ordered-pilot", role_key="owner")
    entitlement = EntitlementSnapshot.all_objects.get(organization=organization)
    entitlement.features["seo.audit.enabled"] = True
    entitlement.quotas["credits.monthly"] = 100
    entitlement.save()
    CreditOperation.objects.create(key="seo.synthetic.audit", name="Synthetic audit", cost=7)
    site = Site.all_objects.create(
        organization=organization, name="Pilot", slug="pilot", created_by=user
    )
    Domain.all_objects.create(
        organization=organization,
        site=site,
        hostname="owned.example.test",
        kind="custom",
        status="verified",
        is_canonical=True,
        created_by=user,
    )
    headers = {
        "Cookie": "; ".join(f"{name}={cookie.value}" for name, cookie in person.cookies.items()),
        "X-CSRFToken": csrf_value(person),
        "Origin": live_server.url,
    }
    with (tmp_path / "ssa-private.log").open("w", encoding="utf-8") as log:
        process = _server(ssa, port, context, log)
        try:
            body = {"site_id": str(site.id), "idempotency_key": "synthetic-audit-purchase"}
            response = _request(live_server.url + "/api/v1/seo/audits/", body=body, headers=headers)
            assert response.status_code == 201, response.text
            order = AuditOrder.all_objects.get(pk=response.json()["id"])
            assert CreditReservation.all_objects.count() == 1
            dispatch_audit(organization.id, order.id)
            order.refresh_from_db()
            assert order.state == "running", order.error_code
            assert order.credit_state == "reserved"
            data["order_id"] = str(order.id)
            context.write_text(json.dumps(data), encoding="utf-8")
            _run(ssa, "complete_order_source", context)
            assert AuditCallbackReceipt.all_objects.filter(order=order).count() == 1
            dispatch_audit(organization.id, order.id)
            order.refresh_from_db()
            assert order.state == outcome, order.error_code
            assert order.credit_state == credit_state
            assert order.report_snapshot["issue_count"] == 101
            assert len(order.report_snapshot["issues"]) == 101
            assert len(order.report_hash) == 64
            repeated = _request(live_server.url + "/api/v1/seo/audits/", body=body, headers=headers)
            assert repeated.status_code == 200, repeated.text
            assert repeated.json()["id"] == str(order.id)
            dispatch_audit(organization.id, order.id)
            assert CreditReservation.all_objects.count() == 1
            assert CreditReservation.all_objects.get().state == credit_state
            report = _request(live_server.url + f"/api/v1/seo/audits/{order.id}/", headers=headers)
            assert report.status_code == 200, report.text
            (tmp_path / "evidence.json").write_text(
                json.dumps(
                    {
                        "synthetic": True,
                        "order_id": str(order.id),
                        "outcome": outcome,
                        "credit_state": credit_state,
                        "synthetic_credit_cost": order.credit_cost,
                        "issue_count": 101,
                        "callback_receipts": 1,
                        "report_hash": order.report_hash,
                        "paid_provider_calls": 0,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        finally:
            process.terminate()
            process.wait(timeout=10)


def test_scr_collects_observation_results_over_http(tmp_path: Path) -> None:
    from django.utils import timezone

    ssa, scr = _peer(tmp_path, "SSA"), _peer(tmp_path, "SCR")
    ssa_port, scr_port = _port(), _port()
    context = tmp_path / "private-context.json"
    data = {
        "ssa_url": f"http://127.0.0.1:{ssa_port}",
        "scr_url": f"http://127.0.0.1:{scr_port}",
        "observations": True,
    }
    context.write_text(json.dumps(data), encoding="utf-8")
    _run(ssa, "seed_source", context)
    data = json.loads(context.read_text(encoding="utf-8"))
    scr[2].update({
        "SSA_SERVICE_BASE_URL": data["ssa_url"],
        "SSA_SERVICE_TOKEN": data["source_key"],
        "SCR_PRODUCT_ID": "scr",
        "SCR_DEPLOYMENT_ID": "local-pilot",
    })
    _run(scr, "seed_scr_projects", context)
    data = json.loads(context.read_text(encoding="utf-8"))
    headers = {"Authorization": f"Bearer {data['workspace_keys']['synthetic-pilot']}"}
    processes = []
    with (tmp_path / "ssa.log").open("w") as ssa_log, (tmp_path / "scr.log").open("w") as scr_log:
        try:
            processes.append(_server(ssa, ssa_port, context, ssa_log))
            processes.append(_server(scr, scr_port, context, scr_log))
            response = _request(
                data["scr_url"] + "/api/v1/projects/",
                body={
                    "name": "Observed site",
                    "root_url": "https://public.example.test/",
                    "purpose": "external",
                },
                headers={**headers, "Idempotency-Key": "observed-project"},
            )
            assert response.status_code == 202, response.text
            project_id = response.json()["id"]
            _run(scr, "provision_scr", context)
            project_url = data["scr_url"] + f"/api/v1/projects/{project_id}/"
            project = _request(project_url, headers=headers).json()
            assert project["status"] == "ready", project
            schedules_url = data["scr_url"] + "/api/v1/observations/schedules/"
            body = {
                "project_id": project_id,
                "module_code": "onsite",
                "options": {"max_pages": 1},
                "starts_at": timezone.now().isoformat(),
                "interval_seconds": 0,
                "max_runs": 1,
            }
            response = _request(
                schedules_url, body=body, headers={**headers, "Idempotency-Key": "one-observation"}
            )
            assert response.status_code == 202, response.text
            schedule_id = response.json()["id"]
            repeat = _request(
                schedules_url, body=body, headers={**headers, "Idempotency-Key": "one-observation"}
            )
            assert repeat.json()["id"] == schedule_id
            _run(scr, "process_scr_observations", context)
            operations_url = schedules_url + f"{schedule_id}/operations/"
            response = _request(operations_url, headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()["count"] == 1
            operation = response.json()["results"][0]
            assert operation["status"] == "running", operation
            data["order_id"] = operation["id"]
            context.write_text(json.dumps(data), encoding="utf-8")
            _run(ssa, "complete_order_source", context)
            operation_url = data["scr_url"] + f"/api/v1/observations/operations/{operation['id']}/"
            response = _request(operation_url + "reconcile/", body={}, headers=headers)
            assert response.status_code == 202, response.text
            _run(scr, "process_scr_observations", context)
            operation = _request(operation_url, headers=headers).json()
            assert operation["status"] == "completed", operation
            assert operation["snapshot_id"]
            response = _request(operation_url + "snapshot/", headers=headers)
            assert response.status_code == 200, response.text
            snapshot = response.json()
            assert snapshot["project_id"] == project_id
            assert snapshot["payload"]["coverage"]["rows_returned"] == 101
            assert len(snapshot["payload"]["measurements"]) == 101
            assert all("details" not in row for row in snapshot["payload"]["measurements"])
            other = {"Authorization": f"Bearer {data['workspace_keys']['synthetic-other']}"}
            assert _request(operation_url + "snapshot/", headers=other).status_code == 404
            _run(scr, "process_scr_observations", context)
            evidence = json.loads(context.read_text(encoding="utf-8"))
            assert evidence["observation_snapshots"] == evidence["project_audit_bindings"] == 1
            assert _request(operations_url, headers=headers).json()["count"] == 1
            assert (
                _request(project_url, headers=headers).json()["ssa_project_id"]
                == project["ssa_project_id"]
            )
            (tmp_path / "evidence.json").write_text(
                json.dumps(
                    {
                        "synthetic": True,
                        "snapshots": 1,
                        "project_audit_bindings": 1,
                        "issues": 101,
                        "private_details_copied": False,
                        "foreign_snapshot_status": 404,
                        "paid_provider_calls": 0,
                        "crawler_calls": 0,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        finally:
            for process in reversed(processes):
                process.terminate()
                process.wait(timeout=10)


def test_scr_provisions_independent_projects_in_ssa(tmp_path: Path) -> None:
    ssa, scr = _peer(tmp_path, "SSA"), _peer(tmp_path, "SCR")
    ssa_port, scr_port = _port(), _port()
    context = tmp_path / "private-context.json"
    data = {"ssa_url": f"http://127.0.0.1:{ssa_port}", "scr_url": f"http://127.0.0.1:{scr_port}"}
    context.write_text(json.dumps(data), encoding="utf-8")
    _run(ssa, "seed_source", context)
    data = json.loads(context.read_text(encoding="utf-8"))
    scr[2].update({
        "SSA_SERVICE_BASE_URL": data["ssa_url"],
        "SSA_SERVICE_TOKEN": data["source_key"],
        "SCR_PRODUCT_ID": "scr",
        "SCR_DEPLOYMENT_ID": "local-pilot",
    })
    _run(scr, "seed_scr_projects", context)
    data = json.loads(context.read_text(encoding="utf-8"))
    processes = []
    with (tmp_path / "ssa.log").open("w") as ssa_log, (tmp_path / "scr.log").open("w") as scr_log:
        try:
            processes.append(_server(ssa, ssa_port, context, ssa_log))
            processes.append(_server(scr, scr_port, context, scr_log))
            projects = {}
            body = {
                "name": "Same public URL",
                "root_url": "https://public.example.test/",
                "purpose": "external",
            }
            for tenant, key in data["workspace_keys"].items():
                headers = {"Authorization": f"Bearer {key}", "Idempotency-Key": "same-project-key"}
                response = _request(
                    f"{data['scr_url']}/api/v1/projects/", body=body, headers=headers
                )
                assert response.status_code == 202, response.text
                assert response.json()["status"] == "provisioning"
                projects[tenant] = response.json()["id"]
                replay = _request(f"{data['scr_url']}/api/v1/projects/", body=body, headers=headers)
                assert replay.json()["id"] == projects[tenant]
            _run(scr, "provision_scr", context)
            upstream = {}
            for tenant, key in data["workspace_keys"].items():
                response = _request(
                    f"{data['scr_url']}/api/v1/projects/{projects[tenant]}/",
                    headers={"Authorization": f"Bearer {key}"},
                )
                assert response.status_code == 200, response.text
                assert response.json()["status"] == "ready", response.text
                upstream[tenant] = response.json()["ssa_project_id"]
            assert len(set(upstream.values())) == 2
            for tenant, project_id in upstream.items():
                headers = {
                    "Authorization": f"Bearer {data['source_key']}",
                    "X-External-Tenant-ID": tenant,
                }
                own = _request(f"{data['ssa_url']}/api/v1/projects/{project_id}/", headers=headers)
                assert own.status_code == 200, own.text
                assert own.json()["audit_runs_count"] == 0
                other = next(value for name, value in upstream.items() if name != tenant)
                assert (
                    _request(
                        f"{data['ssa_url']}/api/v1/projects/{other}/", headers=headers
                    ).status_code
                    == 404
                )
            (tmp_path / "evidence.json").write_text(
                json.dumps(
                    {
                        "synthetic": True,
                        "scr_projects": projects,
                        "ssa_projects": upstream,
                        "same_url_kept_separate": True,
                        "foreign_project_status": 404,
                        "new_analysis_requested": False,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        finally:
            for process in reversed(processes):
                process.terminate()
                process.wait(timeout=10)
