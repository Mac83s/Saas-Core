from unittest.mock import patch
from uuid import UUID

import pytest
from django.test import override_settings
from rest_framework.test import APIClient


def test_liveness_does_not_require_dependencies(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="saas_core.http"):
        response = APIClient().get("/api/v1/health/live/?token=sekret-testowy")

    assert response.status_code == 200
    assert response.json()["checks"] == {"process": "ok"}
    UUID(response.json()["correlation_id"])
    assert response.headers["X-Correlation-ID"] == response.json()["correlation_id"]
    request_log = next(record for record in caplog.records if record.message == "request_completed")
    assert request_log.http_path == "/api/v1/health/live/"
    assert "token" not in request_log.getMessage()


def test_metrics_use_bounded_route_labels_without_query_values() -> None:
    client = APIClient()
    client.get("/api/v1/health/live/?token=sekret-testowy")

    response = client.get("/internal/metrics/")
    payload = response.content.decode()

    assert response.status_code == 200
    assert 'route="api/v1/health/live/"' in payload
    assert "sekret-testowy" not in payload


@override_settings(HEALTH_CHECK_DEPENDENCIES=False)
def test_health_can_run_without_dependency_probes() -> None:
    response = APIClient().get("/api/v1/health/")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["checks"] == {"database": "skipped", "cache": "skipped"}


def test_health_reports_degraded_dependencies() -> None:
    with patch(
        "saas_core.modules.core.health.views._dependency_checks",
        return_value={"database": "error", "cache": "error"},
    ):
        response = APIClient().get("/api/v1/health/")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": "redis://127.0.0.1:6379/15",
        }
    }
)
@pytest.mark.django_db
def test_health_checks_database_and_cache() -> None:
    response = APIClient().get("/api/v1/health/")

    assert response.status_code == 200
    assert response.json()["checks"] == {"database": "ok", "cache": "ok"}
