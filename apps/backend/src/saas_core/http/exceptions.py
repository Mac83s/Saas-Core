from typing import Any

from rest_framework.response import Response
from rest_framework.views import exception_handler


def problem_details_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    response = exception_handler(exc, context)
    if response is None:
        return None

    request = context.get("request")
    correlation_id = getattr(request, "correlation_id", None)
    original = response.data
    detail = original.get("detail", original) if isinstance(original, dict) else original
    response.data = {
        "type": "about:blank",
        "title": "Żądanie nie może zostać obsłużone",
        "status": response.status_code,
        "code": getattr(exc, "default_code", "api_error"),
        "detail": detail,
        "correlation_id": correlation_id,
    }
    response.content_type = "application/problem+json"
    return response
