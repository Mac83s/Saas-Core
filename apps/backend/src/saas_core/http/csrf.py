from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.csrf import csrf_failure as django_csrf_failure


def csrf_failure(
    request: HttpRequest,
    reason: str = "",
    template_name: str = "403_csrf.html",
) -> HttpResponse:
    if not request.path.startswith("/api/"):
        return django_csrf_failure(request, reason=reason, template_name=template_name)

    payload: dict[str, Any] = {
        "type": "about:blank",
        "title": "Żądanie nie może zostać obsłużone",
        "status": 403,
        "code": "csrf_failed",
        "detail": "Brak prawidłowego tokenu CSRF.",
        "correlation_id": getattr(request, "correlation_id", None),
    }
    return JsonResponse(payload, status=403, content_type="application/problem+json")
