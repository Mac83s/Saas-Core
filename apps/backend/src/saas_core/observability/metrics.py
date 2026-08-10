import os
from time import monotonic

from django.http import HttpRequest, HttpResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)

HTTP_REQUESTS = Counter(
    "saas_core_http_requests_total",
    "Liczba zakończonych żądań HTTP.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "saas_core_http_request_duration_seconds",
    "Czas obsługi żądania HTTP.",
    ("method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)


def observe_request(request: HttpRequest, status: int, started_at: float) -> None:
    match = request.resolver_match
    route = match.route if match and match.route else "unmatched"
    allowed_methods = {"GET", "POST", "PUT", "PATCH", "DELETE"}
    method = request.method if request.method in allowed_methods else "OTHER"
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    HTTP_DURATION.labels(method=method, route=route).observe(monotonic() - started_at)


def metrics_view(_request: HttpRequest) -> HttpResponse:
    registry: CollectorRegistry = REGISTRY
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
    return HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)
