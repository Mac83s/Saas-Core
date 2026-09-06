from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest

from saas_core.modules.shared.seo.source import SourceConfig, SourceError, SsaSource


def test_report_pagination_is_bounded_complete_and_omits_private_details(monkeypatch: Any) -> None:
    source, tenant, audit_id, project_id = configured()
    calls = []

    def response(method: str, path: str, tenant_id: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((path, kwargs.get("params")))
        if path.endswith("summary/"):
            return {
                "audit": {
                    "id": str(audit_id),
                    "project": str(project_id),
                    "status": "completed",
                    "private": "secret",
                },
                "score": {"overall_score": 91, "private": "secret"},
            }
        page = kwargs["params"]["page"]
        return {
            "count": 2,
            "next": "https://evil.example/never-follow" if page == 1 else None,
            "results": [
                {"id": str(page), "details": {"private": "secret"}, "rule_code": "TITLE_MISSING"}
            ],
        }

    monkeypatch.setattr(source, "_request", response)
    report = source.report(tenant, audit_run_id=audit_id, project_id=project_id)
    assert report["issue_count"] == 2 and len(calls) == 3
    assert calls[-1][1] == {"page": 2, "page_size": 100}
    assert "secret" not in str(report)
    assert report["score"]["overall_score"] == 91


def configured() -> tuple[SsaSource, Any, Any, Any]:
    return (
        SsaSource(
            SourceConfig(
                "https://ssa.example/api/v1",
                uuid4(),
                "core",
                "test",
                "synthetic-key",
                "synthetic-secret",
                "test.audit",
            )
        ),
        uuid4(),
        uuid4(),
        uuid4(),
    )


@pytest.mark.parametrize(
    "invalid", ["duplicate", "count_changes", "truncated", "too_many", "bytes"]
)
def test_report_refuses_partial_or_unbounded_snapshot(monkeypatch: Any, invalid: str) -> None:
    source, tenant, audit_id, project_id = configured()
    if invalid == "bytes":
        source.config = replace(source.config, response_max_bytes=200)

    def response(method: str, path: str, tenant_id: Any, **kwargs: Any) -> dict[str, Any]:
        if path.endswith("summary/"):
            return {
                "audit": {"id": str(audit_id), "project": str(project_id), "status": "completed"}
            }
        page = kwargs["params"]["page"]
        return {
            "count": 6000
            if invalid == "too_many"
            else (3 if invalid == "count_changes" and page == 2 else 2),
            "next": "more" if page == 1 and invalid != "truncated" else None,
            "results": [
                {"id": "same" if invalid == "duplicate" else str(page), "details": "x" * 300}
            ],
        }

    monkeypatch.setattr(source, "_request", response)
    with pytest.raises(SourceError):
        source.report(tenant, audit_run_id=audit_id, project_id=project_id)
