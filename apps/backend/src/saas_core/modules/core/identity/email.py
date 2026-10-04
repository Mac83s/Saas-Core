from __future__ import annotations

from typing import Protocol
from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import send_mail

from saas_core.mail_hold import holds_address


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


class MfaLockedEmailSender(Protocol):
    def send(self, *, email: str, locale: str) -> None: ...


class DjangoMfaLockedEmailSender:
    """Reaching the code limit means someone had the password or a session,
    so the owner hears about it (platform settings plan 0c)."""

    def send(self, *, email: str, locale: str) -> None:
        limit = settings.MFA_FAILURE_LIMIT
        minutes = settings.MFA_LOCK_SECONDS // 60
        if locale == "en":
            subject = "Too many wrong sign-in codes"
            message = (
                f"{limit} wrong two-factor codes were entered for your account, so no code "
                f"will be accepted for {minutes} minutes.\n\n"
                "A code is asked for only after the password or in a signed-in session. "
                "If it was not you, change your password and sign out your other sessions "
                "in your account settings.\n"
            )
        else:
            subject = "Zbyt wiele błędnych kodów logowania"
            message = (
                f"Na Twoim koncie wpisano {limit} błędnych kodów weryfikacji dwuetapowej, "
                f"więc przez {minutes} minut żaden kod nie zostanie przyjęty.\n\n"
                "Kod jest potrzebny dopiero po haśle albo w zalogowanej sesji. Jeśli to nie "
                "Ty, zmień hasło i wyloguj pozostałe sesje w ustawieniach konta.\n"
            )
        _deliver(email=email, subject=subject, message=message)


class DjangoOperatorMfaResetEmailSender:
    def send(self, *, email: str, locale: str) -> None:
        if locale == "en":
            subject = "Your two-factor sign-in was reset"
            message = (
                "The server administrator reset the two-factor sign-in of your operator "
                "account. All your sessions were signed out and the old recovery codes no "
                "longer work; the administrator sets up the new authenticator.\n\n"
                "If you did not ask for this, contact them at once.\n"
            )
        else:
            subject = "Weryfikacja dwuetapowa konta została zresetowana"
            message = (
                "Administrator serwera zresetował weryfikację dwuetapową Twojego konta "
                "operatora. Wszystkie sesje zostały wylogowane, a dotychczasowe kody "
                "zapasowe przestały działać; nową aplikację ustawia administrator.\n\n"
                "Jeśli to nie na Twoją prośbę, skontaktuj się z nim od razu.\n"
            )
        _deliver(email=email, subject=subject, message=message)


def get_verification_email_sender() -> VerificationEmailSender:
    return DjangoVerificationEmailSender()


def get_password_reset_email_sender() -> PasswordResetEmailSender:
    return DjangoPasswordResetEmailSender()


def get_mfa_locked_email_sender() -> MfaLockedEmailSender:
    return DjangoMfaLockedEmailSender()


def get_operator_mfa_reset_email_sender() -> MfaLockedEmailSender:
    return DjangoOperatorMfaResetEmailSender()


def _deliver(*, email: str, subject: str, message: str) -> None:
    if holds_address(email):
        return
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
