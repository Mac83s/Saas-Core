from __future__ import annotations

import logging

from celery import shared_task

from saas_core.observability import correlation_id

from .email import (
    EmailDeliveryError,
    get_password_reset_email_sender,
    get_verification_email_sender,
)
from .models import EmailVerification, PasswordReset
from .tokens import issue_bound_token

logger = logging.getLogger("saas_core.security")


@shared_task(  # type: ignore[untyped-decorator]
    autoretry_for=(EmailDeliveryError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def send_email_verification(
    verification_id: str,
    request_correlation_id: str | None = None,
) -> None:
    context_token = correlation_id.set(request_correlation_id)
    try:
        try:
            verification = EmailVerification.objects.select_related("user").get(
                pk=verification_id
            )
        except EmailVerification.DoesNotExist:
            return
        if not verification.is_usable():
            return

        issued = issue_bound_token(
            purpose="email-verification",
            identifier=str(verification.id),
        )
        if issued.digest != verification.token_hash:
            return
        get_verification_email_sender().send(
            email=verification.email,
            locale=verification.user.locale,
            token=issued.value,
        )
        logger.info(
            "identity_verification_email_sent",
            extra={
                "security_event": "identity.verification_email_sent",
                "user_id": str(verification.user_id),
            },
        )
    finally:
        correlation_id.reset(context_token)


@shared_task(  # type: ignore[untyped-decorator]
    autoretry_for=(EmailDeliveryError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def send_password_reset(
    reset_id: str,
    request_correlation_id: str | None = None,
) -> None:
    context_token = correlation_id.set(request_correlation_id)
    try:
        try:
            reset = PasswordReset.objects.select_related("user").get(pk=reset_id)
        except PasswordReset.DoesNotExist:
            return
        if not reset.is_usable():
            return
        issued = issue_bound_token(
            purpose="password-reset",
            identifier=str(reset.id),
        )
        if issued.digest != reset.token_hash:
            return
        get_password_reset_email_sender().send(
            email=reset.user.email,
            locale=reset.user.locale,
            token=issued.value,
        )
        logger.info(
            "identity_password_reset_email_sent",
            extra={
                "security_event": "identity.password_reset_email_sent",
                "user_id": str(reset.user_id),
            },
        )
    finally:
        correlation_id.reset(context_token)
