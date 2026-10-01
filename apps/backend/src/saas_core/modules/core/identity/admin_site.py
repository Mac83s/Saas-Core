"""The operator admin at /internal/admin/ trusts only a session that passed MFA.

Django's own admin login checks a password and nothing else, so on a staff
account it was a way around the second factor the panel demands (ADR-023,
ADR-059). This site has no login form at all: an operator signs in through the
panel, where a staff account cannot get a session without MFA, and the admin
accepts that managed session only when this very session carries the mark that
its second factor was checked.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse

from .mfa import has_confirmed_mfa
from .middleware import MANAGED_SESSION_KEY
from .sessions import MFA_VERIFIED_SESSION_KEY

LOGIN_REFUSED = (
    "Panel administracyjny nie ma własnego logowania. Zaloguj się w panelu "
    "aplikacji kontem operatora z MFA, a potem otwórz ten adres ponownie.\n"
)


class MfaAdminSite(admin.AdminSite):
    def has_permission(self, request: HttpRequest) -> bool:
        user = request.user
        return bool(
            user.is_active
            and user.is_staff
            and request.session.get(MANAGED_SESSION_KEY)
            and request.session.get(MFA_VERIFIED_SESSION_KEY)
            and has_confirmed_mfa(user)  # type: ignore[arg-type]
        )

    def login(self, request: HttpRequest, extra_context: Any = None) -> HttpResponse:
        if self.has_permission(request):
            return HttpResponseRedirect(reverse("admin:index", current_app=self.name))
        return HttpResponse(LOGIN_REFUSED, status=403, content_type="text/plain; charset=utf-8")
