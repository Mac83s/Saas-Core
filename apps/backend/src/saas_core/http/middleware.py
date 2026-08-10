import logging
from collections.abc import Callable
from time import monotonic
from typing import Any, cast
from uuid import UUID, uuid7

from django.http import HttpRequest, HttpResponse

from saas_core.observability import correlation_id as correlation_context
from saas_core.observability.metrics import observe_request

CORRELATION_HEADER = "X-Correlation-ID"
logger = logging.getLogger("saas_core.http")


def _correlation_id(value: str | None) -> str:
    if value:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    return str(uuid7())


class CorrelationIdMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        correlation_id = _correlation_id(request.headers.get(CORRELATION_HEADER))
        cast(Any, request).correlation_id = correlation_id
        token = correlation_context.set(correlation_id)
        started_at = monotonic()
        try:
            response = self.get_response(request)
            observe_request(request, response.status_code, started_at)
            response[CORRELATION_HEADER] = correlation_id
            logger.info(
                "request_completed",
                extra={
                    "correlation_id": correlation_id,
                    "duration_ms": round((monotonic() - started_at) * 1000, 2),
                    "http_method": request.method,
                    "http_path": request.path,
                    "http_status": response.status_code,
                },
            )
            return response
        finally:
            correlation_context.reset(token)
