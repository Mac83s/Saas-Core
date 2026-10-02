from typing import Any

from django.core.exceptions import NON_FIELD_ERRORS
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import exception_handler

#: The statuses whose problem also lists `errors` (ADR-076 §5): what the caller
#: can fix in its input (400) and a content operation's refusal (422).
FIELD_ERROR_STATUSES = frozenset({400, 422})

ProblemFieldError = dict[str, str | None]


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


def problem_errors(exc: APIException) -> list[ProblemFieldError]:
    """The problem as `{field, code, message}` entries a caller can act on (ADR-076 §5).

    Only a `ValidationError` is walked: its detail has the shape of the input,
    so a key is a field and a list position an index (`items.1.name`), and a
    non-field key stands for the level above it — `field` is null for the
    request as a whole. Any other exception is one refusal whatever its detail
    holds: a module may keep its own dict there, and walking it would name
    fields the request never had. Such an exception points at a field with
    `problem_field`, the way it names its code with `problem_code`.
    """
    entries: list[ProblemFieldError] = []
    if isinstance(exc, ValidationError):
        _walk(exc.detail, (), entries)
    if not entries:
        detail = exc.detail
        entries.append({
            "field": getattr(exc, "problem_field", None),
            "code": problem_code(exc),
            "message": str(detail) if isinstance(detail, str) else str(exc.default_detail),
        })
    return entries


def _walk(node: Any, path: tuple[str, ...], into: list[ProblemFieldError]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            # DRF's key, and Django's in a model's `message_dict`.
            whole = key in (api_settings.NON_FIELD_ERRORS_KEY, NON_FIELD_ERRORS)
            _walk(value, path if whole else (*path, str(key)), into)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            # A message keeps its field's path; a nested item adds its position.
            _walk(item, path if isinstance(item, str) else (*path, str(index)), into)
    else:
        into.append({
            "field": ".".join(path) or None,
            "code": getattr(node, "code", None) or "invalid",
            "message": str(node),
        })


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
    if response.status_code in FIELD_ERROR_STATUSES and isinstance(exc, APIException):
        # From the exception, not `original`: the unwrap above drops the other
        # keys of a dict that has a `detail` one.
        response.data["errors"] = problem_errors(exc)
    response.content_type = "application/problem+json"
    return response
