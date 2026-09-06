"""Bounded transport to one operator-configured SSA source, never a user URL."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from django.conf import settings
from rest_framework.exceptions import APIException


class SeoUnavailable(APIException):
    status_code = 503
    default_detail = "Integracja audytu nie została skonfigurowana."
    default_code = "seo_unavailable"


class SourceError(Exception):
    def __init__(self, code: str, *, retryable: bool = True, missing: bool = False):
        self.code = code
        self.retryable = retryable
        self.missing = missing
        super().__init__(code)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class SourceConfig:
    base_url: str
    source_id: UUID
    product_id: str
    deployment_id: str
    credential: str = field(repr=False)
    callback_secret: str = field(repr=False)
    credit_operation_key: str
    max_pages: int = 100
    report_max_issues: int = 5000
    response_max_bytes: int = 5_000_000

    @classmethod
    def configured(cls) -> SourceConfig:
        try:
            base_url = str(settings.SEO_SSA_BASE_URL).rstrip("/")
            parsed = urlsplit(base_url)
            credential = str(settings.SEO_SSA_SERVICE_KEY)
            callback_secret = str(settings.SEO_SSA_CALLBACK_SECRET)
            operation = str(settings.SEO_AUDIT_CREDIT_OPERATION)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or not credential
                or not callback_secret
                or not operation
                or not settings.SEO_SSA_PRODUCT_ID
                or not settings.SEO_SSA_DEPLOYMENT_ID
                or not 1 <= int(settings.SEO_AUDIT_MAX_PAGES) <= 10000
                or not 1 <= int(settings.SEO_REPORT_MAX_ISSUES) <= 10000
            ):
                raise ValueError
            return cls(
                base_url=base_url,
                source_id=UUID(str(settings.SEO_SSA_SOURCE_ID)),
                product_id=str(settings.SEO_SSA_PRODUCT_ID),
                deployment_id=str(settings.SEO_SSA_DEPLOYMENT_ID),
                credential=credential,
                callback_secret=callback_secret,
                credit_operation_key=operation,
                max_pages=int(settings.SEO_AUDIT_MAX_PAGES),
                report_max_issues=int(settings.SEO_REPORT_MAX_ISSUES),
            )
        except (AttributeError, ValueError, TypeError) as error:
            raise SeoUnavailable from error


class SsaSource:
    def __init__(self, config: SourceConfig):
        self.config = config

    def _request(
        self,
        method: str,
        path: str,
        tenant_id: UUID,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.config.credential}",
            "X-External-Tenant-ID": str(tenant_id),
        }

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, hdrs, newurl):  # type: ignore[no-untyped-def]
                return None

        url = self.config.base_url + path
        if params:
            url += "?" + urlencode(params)
        data = json.dumps(payload).encode() if payload is not None else None
        headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
                body = response.read(self.config.response_max_bytes + 1)
                if len(body) > self.config.response_max_bytes:
                    raise SourceError("ssa_response_too_large")
                value = json.loads(body)
                if not isinstance(value, dict):
                    raise SourceError("ssa_response_malformed")
                return value
        except urllib.error.HTTPError as error:
            raise SourceError(
                f"ssa_http_{error.code}",
                missing=error.code == 404,
                retryable=error.code >= 500 or error.code == 429,
            ) from error
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise SourceError("ssa_transport_unknown") from error

    def provision(
        self, tenant_id: UUID, *, external_project_id: str, name: str, root_url: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/integration/projects/",
            tenant_id,
            {
                "external_tenant_id": str(tenant_id),
                "external_project_id": external_project_id,
                "name": name,
                "root_url": root_url,
            },
        )

    def start(
        self,
        tenant_id: UUID,
        *,
        external_project_id: str,
        client_reference: UUID,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/integration/audits/",
            tenant_id,
            {
                "external_project_id": external_project_id,
                "client_reference": str(client_reference),
                **options,
            },
        )

    def status(self, tenant_id: UUID, client_reference: UUID) -> dict[str, Any]:
        return self._request("GET", f"/integration/audits/{client_reference}/", tenant_id)

    def report(self, tenant_id: UUID, *, audit_run_id: UUID, project_id: UUID) -> dict[str, Any]:
        summary = self._request("GET", f"/audit-runs/{audit_run_id}/summary/", tenant_id)
        audit = summary.get("audit")
        if (
            not isinstance(audit, dict)
            or str(audit.get("id")) != str(audit_run_id)
            or str(audit.get("project")) != str(project_id)
            or audit.get("status") != "completed"
        ):
            raise SourceError("ssa_report_identity_mismatch")
        issues: list[dict[str, Any]] = []
        seen: set[str] = set()
        count: int | None = None
        page = 1
        accumulated_bytes = len(json.dumps(summary).encode())
        while True:
            batch = self._request(
                "GET",
                f"/audit-runs/{audit_run_id}/issues/",
                tenant_id,
                params={"page": page, "page_size": 100},
            )
            accumulated_bytes += len(json.dumps(batch).encode())
            if accumulated_bytes > self.config.response_max_bytes:
                raise SourceError("ssa_report_too_large")
            total, rows = batch.get("count"), batch.get("results")
            if (
                not isinstance(total, int)
                or isinstance(total, bool)
                or total < 0
                or total > self.config.report_max_issues
                or not isinstance(rows, list)
                or (count is not None and total != count)
            ):
                raise SourceError("ssa_report_incomplete")
            count = total
            for row in rows:
                if not isinstance(row, dict) or not row.get("id") or str(row["id"]) in seen:
                    raise SourceError("ssa_report_incomplete")
                seen.add(str(row["id"]))
                issues.append({
                    key: row.get(key)
                    for key in (
                        "id",
                        "page",
                        "page_url",
                        "resource",
                        "resource_url",
                        "rule_code",
                        "rule_version",
                        "category",
                        "severity",
                        "weight",
                        "message_key",
                        "status",
                        "is_active",
                        "created_at",
                        "updated_at",
                    )
                })
            if len(issues) > self.config.report_max_issues or len(issues) > count:
                raise SourceError("ssa_report_incomplete")
            if batch.get("next") is None:
                if len(issues) != count:
                    raise SourceError("ssa_report_incomplete")
                break
            if not rows or page >= (self.config.report_max_issues // 100 + 1):
                raise SourceError("ssa_report_incomplete")
            page += 1
        return {
            "audit": {
                key: audit.get(key)
                for key in (
                    "id",
                    "project",
                    "status",
                    "started_at",
                    "completed_at",
                    "created_at",
                )
            },
            "score": {
                key: summary["score"].get(key)
                for key in (
                    "overall_score",
                    "category_scores",
                    "issue_counts",
                    "priorities",
                    "total_checks",
                    "passed_checks",
                    "engine_version",
                    "calculated_at",
                )
            }
            if isinstance(summary.get("score"), dict)
            else None,
            "page_counts": summary.get("page_counts"),
            "issue_counts": summary.get("issue_counts"),
            "issues": issues,
            "issue_count": count,
        }
