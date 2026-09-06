"""Isolated test peers. Each process imports exactly one project's Django app."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import django


def seed_ssa(data: dict) -> None:
    from apps.audits.models import AIReadinessScore, AuditRun, Issue, Page, Project
    from apps.entitlements.api_keys import issue
    from apps.entitlements.models import Organization, Plan
    from django.core.management import call_command
    from django.utils import timezone

    call_command("migrate", verbosity=0)
    plan = Plan.objects.create(code="integration-pilot", name="Synthetic pilot", api_access="full")
    org = Organization.objects.create(name="Synthetic pilot owner", plan=plan)
    project = Project.objects.create(organization=org, name="Pilot", root_url=data["page_url"])
    run = AuditRun.objects.create(
        project=project,
        status="completed",
        start_url=data["page_url"],
        max_pages=1,
        pages_crawled=1,
        urls_discovered=1,
        crawl_completeness="complete",
        finished_at=timezone.now(),
    )
    AIReadinessScore.objects.create(audit_run=run, engine_version="0.3.0")
    page = Page.objects.create(
        audit_run=run,
        url=data["page_url"],
        normalized_url=data["page_url"],
        final_url=data["page_url"],
        status_code=200,
        title="Pilot",
        indexable=True,
    )
    # Crossing the API's 100-row page boundary is deliberate.
    Issue.objects.bulk_create([
        Issue(
            audit_run=run,
            page=page,
            rule_code="META_DESCRIPTION_MISSING" if i == 0 else f"PILOT_INFO_{i}",
            category="onpage",
            severity="medium",
            fingerprint=f"{i:064x}",
            message_key="rules.meta_description_missing",
            details={},
        )
        for i in range(101)
    ])
    _, raw = issue(org, name="Synthetic reader", scopes=["projects:read"])
    data.update(ssa_key=raw, project_id=str(project.id), audit_run_id=str(run.id))


def seed_scr(data: dict) -> None:
    from uuid import uuid4

    from django.core.management import call_command
    from seocontentrank.audit.client import SeoSiteAuditClient
    from seocontentrank.audit.service import store_snapshot
    from seocontentrank.targets.models import TargetConnection
    from seocontentrank.targets.resolver import PilotBinding, resolve_content_base
    from seocontentrank.targets.saas_core import SaasCoreAdapter, perform_handshake
    from seocontentrank.tenancy.keys import issue
    from seocontentrank.tenancy.models import Workspace

    call_command("migrate", verbosity=0)
    workspace = Workspace.objects.create(external_tenant_id="synthetic-pilot")
    with SeoSiteAuditClient(data["ssa_url"], data["ssa_key"]) as source:
        assert source.project(data["project_id"])["id"] == data["project_id"]
        run = source.audit_run(data["audit_run_id"])
        pages = list(source.pages(data["audit_run_id"]))
        snapshot, _ = store_snapshot(
            source, data["ssa_url"], run, workspace, project_id=data["project_id"]
        )
    assert snapshot.findings.count() == 101
    assert len(pages) == 1
    target = TargetConnection(
        workspace=workspace, system="saas-core", label="pilot", base_url=data["core_url"]
    )
    target.set_credential(data["core_key"])
    target.save()
    binding = {
        "version": 1,
        "id": str(uuid4()),
        "workspace_id": str(workspace.id),
        "source": {
            "snapshot_id": str(snapshot.id),
            "base_url": data["ssa_url"],
            "project_id": data["project_id"],
            "audit_run_id": data["audit_run_id"],
            "page_url": data["page_url"],
        },
        "target": {
            "connection_id": str(target.id),
            "base_url": data["core_url"],
            "site_id": data["site_id"],
            "page_id": data["page_id"],
            "locale": "pl",
        },
    }
    with SaasCoreAdapter(target.base_url, target.reveal_credential()) as adapter:
        perform_handshake(target, adapter, workspace=workspace)
        state = resolve_content_base(PilotBinding.parse(binding), adapter, workspace=workspace)
    finding = snapshot.findings.get(rule_code="META_DESCRIPTION_MISSING")
    payload = {
        "contract_version": "1.0.0",
        "idempotency_key": "synthetic-pilot-metadata-001",
        "mode": data.get("mode", "suggest_only"),
        "target": {
            "system": "saas_core",
            "resource_type": "page",
            "resource_id": data["page_id"],
            "locale": "pl",
        },
        "base": {
            "version": str(state["base"]["version"]),
            "content_hash": state["base"]["snapshot_hash"].removeprefix("sha256:"),
            "observed_at": state["observed_at"],
        },
        "input": {
            "observed_at": snapshot.observed_at.isoformat(),
            "engine_version": snapshot.engine_version,
            "crawl_completeness": snapshot.crawl_completeness,
            "is_truncated": snapshot.is_truncated,
        },
        "commands": [
            {
                "op": "set_meta_description",
                "value": "Synthetic test: a proposed description for a local integration preview.",
            }
        ],
        "rationale": {
            "summary": "The synthetic audit found a missing description.",
            "risk": "low",
            "sources": [
                {
                    "system": "seositeaudit",
                    "kind": "issue",
                    "ref": f"META_DESCRIPTION_MISSING@{data['page_url']}",
                }
            ],
        },
    }
    _, key = issue(
        workspace, name="Pilot API", scopes=["proposals:read", "proposals:write", "targets:manage"]
    )
    data.update(
        binding=binding,
        scr_key=key,
        proposal_request={
            "snapshot_id": str(snapshot.id),
            "finding_id": str(finding.id),
            "payload": payload,
        },
        imported_findings=101,
        imported_pages=1,
    )


def preview_scr(data: dict) -> None:
    from seocontentrank.targets.pilot import preview_proposal
    from seocontentrank.targets.resolver import PilotBinding
    from seocontentrank.targets.saas_core import SaasCoreAdapter
    from seocontentrank.tenancy.authentication import Actor
    from seocontentrank.tenancy.models import Workspace

    workspace = Workspace.objects.get(external_tenant_id="synthetic-pilot")
    actor = Actor(workspace, "synthetic-pilot", frozenset({"proposals:read", "targets:manage"}))
    with SaasCoreAdapter(data["core_url"], data["core_key"]) as adapter:
        report = preview_proposal(
            actor=actor,
            proposal_id=data["proposal_id"],
            binding=PilotBinding.parse(data["binding"]),
            adapter=adapter,
        )
    data["report"] = report


def seed_source(data: dict) -> None:
    from apps.entitlements.models import Plan
    from apps.integrations.keys import issue
    from apps.integrations.models import IntegrationSource
    from django.core.management import call_command

    call_command("migrate", verbosity=0)
    plan = Plan.objects.create(code="source-pilot", name="Synthetic source", api_access="full")
    source = IntegrationSource.objects.create(
        product_id="scr", deployment_id="local-pilot", plan=plan, callback_recipient="pilot"
    )
    _, secret = issue(source, name="Pilot", scopes=["integration:provision", "projects:read"])
    data.update(source_key=secret, source_id=str(source.id))


def seed_scr_projects(data: dict) -> None:
    from django.core.management import call_command
    from seocontentrank.tenancy.keys import issue
    from seocontentrank.tenancy.models import Workspace

    call_command("migrate", verbosity=0)
    data["workspace_keys"] = {}
    for external_id in ("synthetic-pilot", "synthetic-other"):
        workspace = Workspace.objects.create(external_tenant_id=external_id)
        _, key = issue(workspace, name="Pilot", scopes=["projects:read", "projects:write"])
        data["workspace_keys"][external_id] = key


def seed_order_source(data: dict) -> None:
    from apps.entitlements.models import Organization
    from apps.integrations.keys import issue
    from apps.integrations.models import IntegrationSource
    from django.core.management import call_command

    call_command("migrate", verbosity=0)
    call_command("seed_plans", verbosity=0)
    source = IntegrationSource.objects.create(
        product_id="saas-core",
        deployment_id="local-pilot",
        plan=Organization.objects.get(is_default=True).plan,
        callback_recipient="pilot",
    )
    _, key = issue(
        source,
        name="Synthetic Core",
        scopes=[
            "integration:provision",
            "projects:read",
            "audits:run",
        ],
    )
    data.update(source_id=str(source.id), source_key=key)


def complete_order_source(data: dict) -> None:
    """Complete synthetic evidence only; no crawler or provider is executed."""
    from apps.audits.models import AuditJob, AuditRun, AuditScore, Issue, Page
    from apps.integrations.models import IntegrationAuditOperation
    from apps.modules.callback import deliver
    from apps.modules.models import ModuleRun
    from django.utils import timezone

    operation = IntegrationAuditOperation.objects.get(client_reference=data["order_id"])
    run = operation.audit_run
    AuditRun.objects.filter(pk=run.pk).update(
        status="completed",
        pages_crawled=1,
        urls_discovered=1,
        crawl_completeness="complete",
        finished_at=timezone.now(),
    )
    AuditJob.objects.filter(audit_run=run).update(status="succeeded")
    AuditScore.objects.create(audit_run=run, overall_score=80, engine_version="synthetic-1")
    page = Page.objects.create(
        audit_run=run,
        url=run.start_url,
        normalized_url=run.start_url,
        final_url=run.start_url,
        status_code=200,
        title="Synthetic",
        indexable=True,
    )
    Issue.objects.bulk_create([
        Issue(
            audit_run=run,
            page=page,
            rule_code=f"PILOT_{index}",
            category="onpage",
            severity="medium",
            fingerprint=f"{index:064x}",
            message_key="pilot",
            details={},
        )
        for index in range(101)
    ])
    ledger = ModuleRun.objects.get(module_code="onsite", run_reference=str(run.pk))
    ledger.status = data.get("outcome", "completed")
    ledger.finished_at = timezone.now()
    ledger.save(update_fields=["status", "finished_at"])
    # The real callback sender signs and sends both deliveries to Core.
    assert deliver(str(ledger.pk))
    assert deliver(str(ledger.pk))
    data.update(remote_audit_id=str(run.pk), remote_module_id=str(ledger.pk))


def provision_scr(data: dict) -> None:
    from django.core.management import call_command

    call_command("provision_projects", limit=25, verbosity=0)


def seed_scr_blueprint(data: dict) -> None:
    from django.core.management import call_command
    from seocontentrank.targets.models import TargetConnection
    from seocontentrank.tenancy.keys import issue
    from seocontentrank.tenancy.models import Workspace

    call_command("migrate", verbosity=0)
    workspace = Workspace.objects.create(external_tenant_id="synthetic-brief-pilot")
    target = TargetConnection(
        workspace=workspace, system="saas_core", label="Core", base_url=data["core_url"]
    )
    target.set_credential(data["core_key"])
    target.save()
    _, key = issue(
        workspace,
        name="Synthetic brief",
        scopes=["blueprints:read", "blueprints:write", "targets:manage"],
    )
    data.update(connection_id=str(target.id), scr_key=key)


def generate_scr_blueprint(data: dict) -> None:
    from types import SimpleNamespace
    from unittest.mock import patch

    from seocontentrank.audit.models import AuditSnapshot
    from seocontentrank.blueprints import worker
    from seocontentrank.blueprints.models import BriefGeneration
    from seocontentrank.generation.models import GenerationCall

    row = BriefGeneration.objects.get(pk=data["generation_id"])
    template = next(item for item in row.catalog["templates"] if item["id"] == row.template_id)
    slots = {slot["key"]: "Synthetic reviewed copy" for slot in template["slots"]}
    attempt = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=100,
        cost_usd=None,
        usage_reported=True,
        outcome_unknown=False,
    )
    completion = SimpleNamespace(text=json.dumps(slots), attempts=[attempt])
    with patch.object(worker.OpenRouterClient, "complete", return_value=completion) as provider:
        assert worker.run_once() == row.id
        assert provider.call_count == 1
    row.refresh_from_db()
    assert row.status == "review"
    assert not AuditSnapshot.objects.exists()
    assert GenerationCall.objects.count() == 1
    data.update(provider_calls=1, used_prior_audit=False)


if __name__ == "__main__":
    django.setup()
    action, context_path = sys.argv[1:3]
    context = Path(context_path)
    data = json.loads(context.read_text(encoding="utf-8"))
    if action == "serve":
        from wsgiref.simple_server import make_server

        from django.core.wsgi import get_wsgi_application

        with make_server("127.0.0.1", int(sys.argv[3]), get_wsgi_application()) as server:
            server.serve_forever()
    else:
        {
            "seed_ssa": seed_ssa,
            "seed_scr": seed_scr,
            "preview_scr": preview_scr,
            "seed_source": seed_source,
            "seed_scr_projects": seed_scr_projects,
            "provision_scr": provision_scr,
            "seed_order_source": seed_order_source,
            "complete_order_source": complete_order_source,
            "seed_scr_blueprint": seed_scr_blueprint,
            "generate_scr_blueprint": generate_scr_blueprint,
        }[action](data)
        context.write_text(json.dumps(data, indent=2), encoding="utf-8")
