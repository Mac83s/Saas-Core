from __future__ import annotations

from typing import Protocol
from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import send_mail


class InvitationEmailDeliveryError(RuntimeError):
    pass


class InvitationEmailSender(Protocol):
    def send(
        self,
        *,
        email: str,
        locale: str,
        organization_name: str,
        role_name: str,
        token: str,
    ) -> None: ...


class DjangoInvitationEmailSender:
    def send(
        self,
        *,
        email: str,
        locale: str,
        organization_name: str,
        role_name: str,
        token: str,
    ) -> None:
        locale_prefix = "/en" if locale == "en" else ""
        link = (
            f"{settings.FRONTEND_BASE_URL.rstrip('/')}{locale_prefix}/invitations/accept?"
            f"{urlencode({'token': token})}"
        )
        if locale == "en":
            subject = f"Invitation to {organization_name}"
            message = (
                f"You were invited to {organization_name} as {role_name}.\n\n"
                f"Accept the invitation:\n{link}\n"
            )
        else:
            subject = f"Zaproszenie do {organization_name}"
            message = (
                f"Otrzymujesz zaproszenie do {organization_name} z rolą {role_name}.\n\n"
                f"Przyjmij zaproszenie:\n{link}\n"
            )
        try:
            delivered = send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
        except Exception as error:
            raise InvitationEmailDeliveryError("Provider poczty odrzucił zaproszenie") from error
        if delivered != 1:
            raise InvitationEmailDeliveryError(
                "Provider poczty nie potwierdził dostarczenia zaproszenia"
            )


def get_invitation_email_sender() -> InvitationEmailSender:
    return DjangoInvitationEmailSender()
