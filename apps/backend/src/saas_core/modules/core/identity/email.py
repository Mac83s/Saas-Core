from __future__ import annotations

from typing import Protocol
from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import send_mail


class EmailDeliveryError(RuntimeError):
    """A transient provider failure that Celery may retry."""


class VerificationEmailSender(Protocol):
    def send(self, *, email: str, locale: str, token: str) -> None: ...


class DjangoVerificationEmailSender:
    def send(self, *, email: str, locale: str, token: str) -> None:
        link = (
            f"{settings.FRONTEND_BASE_URL.rstrip('/')}/verify-email?"
            f"{urlencode({'token': token})}"
        )
        if locale == "en":
            subject = "Verify your email address"
            message = f"Open this link to verify your account:\n\n{link}\n"
        else:
            subject = "Potwierdź adres e-mail"
            message = f"Otwórz ten link, aby potwierdzić konto:\n\n{link}\n"
        try:
            delivered = send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
        except Exception as error:
            raise EmailDeliveryError("Provider poczty odrzucił wiadomość") from error
        if delivered != 1:
            raise EmailDeliveryError("Provider poczty nie potwierdził dostarczenia")


def get_verification_email_sender() -> VerificationEmailSender:
    return DjangoVerificationEmailSender()
