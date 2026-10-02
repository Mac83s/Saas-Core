"""Marks the calls made while an HTTP request is handled (ADR-068 pkt 5).

Only those calls share the per-process limiter and have their time cut to
the graceful-shutdown window; a worker calling the same task has neither.
"""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .service import web_request


class ModelPortWebCallMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        with web_request():
            return self.get_response(request)
