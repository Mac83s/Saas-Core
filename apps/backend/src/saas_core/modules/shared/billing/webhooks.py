from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import stripe
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

from .models import StripeWebhookEvent, WebhookProcessingStatus

logger = logging.getLogger("saas_core.billing")


class InvalidStripeWebhook(ValueError):
    pass


class StripeWebhookConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WebhookReceipt:
    event: StripeWebhookEvent
    created: bool


@transaction.atomic
def ingest_stripe_webhook(*, payload: bytes, signature: str) -> WebhookReceipt:
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise ImproperlyConfigured("STRIPE_WEBHOOK_SECRET jest wymagany")
    if not signature:
        raise InvalidStripeWebhook("Brak podpisu Stripe.")
    if not payload or len(payload) > settings.STRIPE_WEBHOOK_MAX_BYTES:
        raise InvalidStripeWebhook("Nieprawidłowy rozmiar webhooka Stripe.")

    try:
        stripe.Webhook.construct_event(  # type: ignore[no-untyped-call]
            payload,
            signature,
            settings.STRIPE_WEBHOOK_SECRET,
            tolerance=settings.STRIPE_WEBHOOK_TOLERANCE_SECONDS,
        )
    except (ValueError, stripe.SignatureVerificationError) as error:
        raise InvalidStripeWebhook("Podpis webhooka Stripe jest nieprawidłowy.") from error

    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise InvalidStripeWebhook("Webhook Stripe nie jest obiektem JSON.")
    event: dict[str, Any] = parsed
    event_id = _required_string(event, "id")
    event_type = _required_string(event, "type")
    api_version = _required_string(event, "api_version")
    livemode = event.get("livemode")
    provider_created = event.get("created")
    if not isinstance(livemode, bool):
        raise InvalidStripeWebhook("Webhook Stripe nie zawiera poprawnego trybu.")
    if (
        not isinstance(provider_created, int)
        or isinstance(provider_created, bool)
        or provider_created < 0
    ):
        raise InvalidStripeWebhook("Webhook Stripe nie zawiera poprawnego czasu.")
    if api_version != settings.STRIPE_API_VERSION:
        raise InvalidStripeWebhook("Nieobsługiwana wersja API webhooka Stripe.")
    if livemode != settings.STRIPE_LIVEMODE:
        raise InvalidStripeWebhook("Webhook Stripe pochodzi z innego trybu konta.")

    provider_created_at = datetime.fromtimestamp(provider_created, tz=UTC)
    stored, created = StripeWebhookEvent.objects.get_or_create(
        stripe_event_id=event_id,
        defaults={
            "event_type": event_type,
            "api_version": api_version,
            "livemode": livemode,
            "provider_created_at": provider_created_at,
            "payload": event,
            "signature_verified_at": timezone.now(),
        },
    )
    if not created and (
        stored.event_type != event_type
        or stored.api_version != api_version
        or stored.livemode != livemode
        or stored.provider_created_at != provider_created_at
        or stored.payload != event
    ):
        raise StripeWebhookConflict("Event ID Stripe wskazuje inną treść.")
    if stored.status not in {
        WebhookProcessingStatus.PROCESSED,
        WebhookProcessingStatus.IGNORED,
    }:
        transaction.on_commit(lambda: _enqueue_processing(stored.id))
    return WebhookReceipt(stored, created)


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise InvalidStripeWebhook(f"Webhook Stripe nie zawiera pola {key}.")
    return value


def _enqueue_processing(event_id: UUID) -> None:
    from .tasks import process_stripe_webhook

    try:
        process_stripe_webhook.delay(str(event_id))
    except Exception:
        logger.exception(
            "stripe_webhook_enqueue_failed",
            extra={"stripe_webhook_event_id": str(event_id)},
        )
