from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, cast

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils.module_loading import import_string


@dataclass(frozen=True, slots=True)
class ProviderMessage:
    id: str
    status: str


class EmailProvider(Protocol):
    def send(
        self,
        *,
        recipient: str,
        subject: str,
        html_body: str,
        idempotency_key: str,
    ) -> ProviderMessage: ...

    def status_for_idempotency_key(self, idempotency_key: str) -> ProviderMessage | None: ...


class DjangoEmailProvider:
    """Local/runtime adapter. Commercial adapters must preserve the same idempotency key."""

    _accepted: dict[str, ProviderMessage] = {}

    def send(
        self,
        *,
        recipient: str,
        subject: str,
        html_body: str,
        idempotency_key: str,
    ) -> ProviderMessage:
        accepted = self._accepted.get(idempotency_key)
        if accepted is not None:
            return accepted
        provider_id = "django:" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]
        message = EmailMessage(
            subject=subject,
            body=html_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
            headers={"X-Idempotency-Key": idempotency_key},
        )
        message.content_subtype = "html"
        message.send(fail_silently=False)
        result = ProviderMessage(id=provider_id, status="sent")
        self._accepted[idempotency_key] = result
        return result

    def status_for_idempotency_key(self, idempotency_key: str) -> ProviderMessage | None:
        return self._accepted.get(idempotency_key)


def get_email_provider() -> EmailProvider:
    provider_class = import_string(settings.NOTIFICATIONS_EMAIL_PROVIDER)
    return cast("EmailProvider", provider_class())
