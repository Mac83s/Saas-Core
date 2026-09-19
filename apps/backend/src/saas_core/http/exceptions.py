from typing import Any

from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler


def problem_code(exc: Exception) -> str:
    """The machine-readable code of a problem.

    An exception may name it explicitly (`problem_code`), or carry it on a
    plain-text detail (`raise NotFound("…", code="catalog_not_found")`);
    otherwise the class's `default_code`. Without the middle case a module
    raising one exception class with several codes answered with the class's
    code only, whatever it documented.
    """
    explicit = getattr(exc, "problem_code", None)
    if explicit:
        return str(explicit)
    if isinstance(exc, APIException):
        codes = exc.get_codes()
        if isinstance(codes, str):
            return codes
    return str(getattr(exc, "default_code", "api_error"))


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
        "code": problem_code(exc),
        "detail": detail,
        "correlation_id": correlation_id,
    }
    response.content_type = "application/problem+json"
    return response
