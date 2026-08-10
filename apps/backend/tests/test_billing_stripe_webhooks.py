from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from saas_core.modules.shared.billing.models import StripeWebhookEvent
from saas_core.modules.shared.billing.tasks import process_stripe_webhook

pytestmark = pytest.mark.django_db

WEBHOOK_SECRET = "whsec_local_test_only"
API_VERSION = "2026-07-29.dahlia"


def event_payload(
    *,
    event_id: str = "evt_valid",
    event_type: str = "checkout.session.completed",
    api_version: str = API_VERSION,
    livemode: bool = False,
    created: int | None = None,
) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "object": "event",
            "api_version": api_version,
            "created": created if created is not None else int(time.time()),
            "data": {"object": {"id": "cs_test_local", "object": "checkout.session"}},
            "livemode": livemode,
            "type": event_type,
        },
        separators=(",", ":"),
    ).encode()


def signature(payload: bytes, *, timestamp: int | None = None) -> str:
    signed_at = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{signed_at}.".encode() + payload
    digest = hmac.new(WEBHOOK_SECRET.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={signed_at},v1={digest}"


def post_webhook(client: Client, payload: bytes, *, header: str | None) -> Any:
    extra = {"HTTP_STRIPE_SIGNATURE": header} if header is not None else {}
    return client.post(
        reverse("billing-stripe-webhook"),
        data=payload,
        content_type="application/json",
        **extra,
    )


@override_settings(
    STRIPE_WEBHOOK_SECRET=WEBHOOK_SECRET,
    STRIPE_API_VERSION=API_VERSION,
    STRIPE_LIVEMODE=False,
    STRIPE_WEBHOOK_TOLERANCE_SECONDS=300,
    STRIPE_WEBHOOK_MAX_BYTES=262_144,
)
def test_valid_signed_event_is_persisted_only_after_verification(client: Client) -> None:
    payload = event_payload()

    response = post_webhook(client, payload, header=signature(payload))

    assert response.status_code == 202
    assert response.json() == {"received": True}
    stored = StripeWebhookEvent.objects.get(stripe_event_id="evt_valid")
    assert stored.event_type == "checkout.session.completed"
    assert stored.api_version == API_VERSION
    assert stored.livemode is False
    assert stored.payload["data"]["object"]["id"] == "cs_test_local"
    assert stored.signature_verified_at is not None


@override_settings(
    STRIPE_WEBHOOK_SECRET=WEBHOOK_SECRET,
    STRIPE_API_VERSION=API_VERSION,
    STRIPE_LIVEMODE=False,
    STRIPE_WEBHOOK_TOLERANCE_SECONDS=300,
    STRIPE_WEBHOOK_MAX_BYTES=262_144,
)
def test_duplicate_signed_delivery_is_idempotent(client: Client) -> None:
    payload = event_payload(event_id="evt_duplicate")
    header = signature(payload)

    first = post_webhook(client, payload, header=header)
    second = post_webhook(client, payload, header=header)

    assert first.status_code == 202
    assert second.status_code == 200
    assert StripeWebhookEvent.objects.filter(stripe_event_id="evt_duplicate").count() == 1


@pytest.mark.parametrize("header", [None, "t=1,v1=invalid"])
@override_settings(
    STRIPE_WEBHOOK_SECRET=WEBHOOK_SECRET,
    STRIPE_API_VERSION=API_VERSION,
    STRIPE_LIVEMODE=False,
    STRIPE_WEBHOOK_TOLERANCE_SECONDS=300,
    STRIPE_WEBHOOK_MAX_BYTES=262_144,
)
def test_missing_or_invalid_signature_is_rejected_before_persistence(
    client: Client,
    header: str | None,
) -> None:
    response = post_webhook(client, event_payload(), header=header)

    assert response.status_code == 400
    assert StripeWebhookEvent.objects.count() == 0


@override_settings(
    STRIPE_WEBHOOK_SECRET=WEBHOOK_SECRET,
    STRIPE_API_VERSION=API_VERSION,
    STRIPE_LIVEMODE=False,
    STRIPE_WEBHOOK_TOLERANCE_SECONDS=30,
    STRIPE_WEBHOOK_MAX_BYTES=262_144,
)
def test_stale_signature_is_rejected(client: Client) -> None:
    payload = event_payload()
    response = post_webhook(client, payload, header=signature(payload, timestamp=1))

    assert response.status_code == 400
    assert StripeWebhookEvent.objects.count() == 0


@pytest.mark.parametrize(
    ("changes", "expected_status"),
    [
        ({"api_version": "2025-07-30.basil"}, 400),
        ({"livemode": True}, 400),
    ],
)
@override_settings(
    STRIPE_WEBHOOK_SECRET=WEBHOOK_SECRET,
    STRIPE_API_VERSION=API_VERSION,
    STRIPE_LIVEMODE=False,
    STRIPE_WEBHOOK_TOLERANCE_SECONDS=300,
    STRIPE_WEBHOOK_MAX_BYTES=262_144,
)
def test_wrong_api_version_or_account_mode_is_rejected(
    client: Client,
    changes: dict[str, Any],
    expected_status: int,
) -> None:
    payload = event_payload(**changes)
    response = post_webhook(client, payload, header=signature(payload))

    assert response.status_code == expected_status
    assert StripeWebhookEvent.objects.count() == 0


@override_settings(
    STRIPE_WEBHOOK_SECRET=WEBHOOK_SECRET,
    STRIPE_API_VERSION=API_VERSION,
    STRIPE_LIVEMODE=False,
    STRIPE_WEBHOOK_TOLERANCE_SECONDS=300,
    STRIPE_WEBHOOK_MAX_BYTES=262_144,
)
def test_same_event_id_with_different_signed_content_is_conflict(client: Client) -> None:
    first_payload = event_payload(event_id="evt_conflict")
    second_payload = event_payload(
        event_id="evt_conflict",
        event_type="customer.subscription.deleted",
    )

    assert post_webhook(client, first_payload, header=signature(first_payload)).status_code == 202
    conflict = post_webhook(client, second_payload, header=signature(second_payload))

    assert conflict.status_code == 409
    assert StripeWebhookEvent.objects.filter(stripe_event_id="evt_conflict").count() == 1


@override_settings(
    STRIPE_WEBHOOK_SECRET="",
    STRIPE_API_VERSION=API_VERSION,
    STRIPE_LIVEMODE=False,
    STRIPE_WEBHOOK_TOLERANCE_SECONDS=300,
    STRIPE_WEBHOOK_MAX_BYTES=262_144,
)
def test_missing_server_webhook_secret_is_service_unavailable(client: Client) -> None:
    payload = event_payload()
    response = post_webhook(client, payload, header=signature(payload))

    assert response.status_code == 503
    assert StripeWebhookEvent.objects.count() == 0


@override_settings(
    STRIPE_WEBHOOK_SECRET=WEBHOOK_SECRET,
    STRIPE_API_VERSION=API_VERSION,
    STRIPE_LIVEMODE=False,
    STRIPE_WEBHOOK_TOLERANCE_SECONDS=300,
    STRIPE_WEBHOOK_MAX_BYTES=262_144,
)
def test_persisted_event_is_enqueued_only_after_commit(
    client: Client,
    django_capture_on_commit_callbacks,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[str] = []
    monkeypatch.setattr(process_stripe_webhook, "delay", scheduled.append)
    payload = event_payload(event_id="evt_scheduled")

    with django_capture_on_commit_callbacks(execute=True):
        response = post_webhook(client, payload, header=signature(payload))

    stored = StripeWebhookEvent.objects.get(stripe_event_id="evt_scheduled")
    assert response.status_code == 202
    assert scheduled == [str(stored.id)]
