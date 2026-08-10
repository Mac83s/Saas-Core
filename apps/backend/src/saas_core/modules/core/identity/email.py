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
        _deliver(email=email, subject=subject, message=message)


class PasswordResetEmailSender(Protocol):
    def send(self, *, email: str, locale: str, token: str) -> None: ...


class DjangoPasswordResetEmailSender:
    def send(self, *, email: str, locale: str, token: str) -> None:
        link = (
            f"{settings.FRONTEND_BASE_URL.rstrip('/')}/reset-password?"
            f"{urlencode({'token': token})}"
        )
        if locale == "en":
            subject = "Reset your password"
            message = f"Open this link to set a new password:\n\n{link}\n"
        else:
            subject = "Ustaw nowe hasło"
            message = f"Otwórz ten link, aby ustawić nowe hasło:\n\n{link}\n"
        _deliver(email=email, subject=subject, message=message)


def get_verification_email_sender() -> VerificationEmailSender:
    return DjangoVerificationEmailSender()


def get_password_reset_email_sender() -> PasswordResetEmailSender:
    return DjangoPasswordResetEmailSender()


def _deliver(*, email: str, subject: str, message: str) -> None:
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
