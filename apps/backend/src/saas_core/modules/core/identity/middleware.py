from collections.abc import Callable
from datetime import timedelta
from typing import Any, cast

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from .models import User, UserSession
from .tokens import digest_secret

MANAGED_SESSION_KEY = "identity_user_session_id"


class ManagedUserSessionMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith("/api/v1/") and request.user.is_authenticated:
            self._validate(request)
        return self.get_response(request)

    def _validate(self, request: HttpRequest) -> None:
        now = timezone.now()
        managed_session_id = request.session.get(MANAGED_SESSION_KEY)
        session_key = request.session.session_key
        invalid = not isinstance(managed_session_id, str) or session_key is None
        tracking = None
        if not invalid:
            user = cast(User, request.user)
            assert user.pk is not None
            assert isinstance(managed_session_id, str)
            assert session_key is not None
            tracking = UserSession.objects.filter(
                pk=managed_session_id,
                user_id=user.pk,
            ).first()
            invalid = (
                tracking is None
                or tracking.session_key_hash != digest_secret(session_key)
                or tracking.revoked_at is not None
                or tracking.expires_at <= now
                or tracking.last_seen_at
                <= now - timedelta(seconds=settings.SESSION_IDLE_TIMEOUT_SECONDS)
            )

        if invalid or tracking is None:
            if tracking is not None and tracking.revoked_at is None:
                UserSession.objects.filter(pk=tracking.pk, revoked_at__isnull=True).update(
                    revoked_at=now
                )
            logout(request)
            return

        updated = UserSession.objects.filter(
            pk=tracking.pk,
            revoked_at__isnull=True,
            expires_at__gt=now,
            last_seen_at__gt=now
            - timedelta(seconds=settings.SESSION_IDLE_TIMEOUT_SECONDS),
        ).update(last_seen_at=now)
        if updated != 1:
            logout(request)
            return

        remaining_max_age = max(1, int((tracking.expires_at - now).total_seconds()))
        request.session.set_expiry(
            min(settings.SESSION_IDLE_TIMEOUT_SECONDS, remaining_max_age)
        )
        cast(Any, request).identity_user_session = tracking
