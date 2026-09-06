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
from test_sites_api import create_page, create_site, save_draft, sites_client  # noqa: E402
from test_sites_operations import _api_key_client  # noqa: E402

pytestmark = pytest.mark.django_db(transaction=True)
HELPER = Path(__file__).with_name("seo_pilot_peer.py")


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


def test_existing_audit_to_retained_proposal_to_core_preview(
    live_server, tmp_path: Path, settings
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
    grant = ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=key.id,
        site_id=site,
        mode="suggest_only",
        created_by=owner,
    )
    ssa_port, scr_port = _port(), _port()
    context = tmp_path / "private-context.json"
    data = {
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
            _run(scr, "preview_scr", context)
            data = json.loads(context.read_text(encoding="utf-8"))
            report = data["report"]
            assert report["preview"]["accepted"] is True, report
            assert report["base_unchanged"] is True
            assert before == (PageVersion.all_objects.count(), Publication.all_objects.count())
            assert PageTranslation.all_objects.get(page_id=page, locale="pl").description == ""
            assert not report["apply_requested"] and not report["publish_requested"]
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
