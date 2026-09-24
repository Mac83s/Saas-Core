"""The OpenAI image adapter against a fake transport: no socket to a provider, no key.

What the caller decides from an error is the kind, so each mapping row of
ADR-059 has a case here; a wrong kind means either paying twice (unknown taken
for retryable) or giving up on a request that never ran.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import threading
import urllib.error
from collections.abc import Iterator
from io import BytesIO
from typing import Any

import pytest

from saas_core.modules.shared.image_generation import provider
from saas_core.modules.shared.image_generation.provider import (
    ImageRequest,
    ProviderError,
    generate,
)

KEY = "test-image-key-not-a-secret"
PROMPT = "A barn at dawn, prompt-marker-7d1f"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


class FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None):
        self._body = BytesIO(body)
        self.headers = headers or {"x-request-id": "req_123"}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self._body.read(amount)


class FakeOpener:
    def __init__(self, outcome: Any):
        self.outcome = outcome
        self.calls: list[Any] = []

    def open(self, request: Any, timeout: float) -> Any:
        self.calls.append((request, timeout))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def success(**usage: Any) -> FakeResponse:
    return FakeResponse(
        json.dumps({
            "data": [{"b64_json": base64.b64encode(JPEG).decode()}],
            "usage": usage
            or {
                "input_tokens": 300,
                "output_tokens": 6000,
                "input_tokens_details": {"text_tokens": 100, "image_tokens": 200},
            },
        }).encode()
    )


def http_error(status: int, code: str = "", error_type: str = "") -> urllib.error.HTTPError:
    body = json.dumps({"error": {"code": code, "type": error_type}}).encode()
    return urllib.error.HTTPError(
        "https://example.invalid",
        status,
        "error",
        {},
        BytesIO(body),  # type: ignore[arg-type]
    )


def request(**overrides: Any) -> ImageRequest:
    return ImageRequest(
        prompt=PROMPT, width=1536, height=1024, end_user="membership-1", **overrides
    )


def call(outcome: Any, **overrides: Any) -> tuple[Any, FakeOpener]:
    opener = FakeOpener(outcome)
    return (
        generate(
            request(**overrides),
            model="gpt-image-2.5-flare-2026-09-08",
            api_key=KEY,
            base_url="https://api.test/v1",
            opener=opener,
        ),
        opener,
    )


def test_success_decodes_the_image_and_prices_it_from_usage() -> None:
    image, opener = call(success())

    assert image.content == JPEG
    assert image.content_type == "image/jpeg"
    assert image.provider_request_id == "req_123"
    # 100 text × 5 + 200 image × 8 + 6000 output × 30 micro-USD.
    assert image.cost_usd_micros == 100 * 5 + 200 * 8 + 6000 * 30
    assert opener.calls[0][1] == 150


def test_generations_body_is_moderated_single_jpeg_with_a_hashed_user() -> None:
    _, opener = call(success())
    sent, _ = opener.calls[0]
    body = json.loads(sent.data)

    assert sent.full_url == "https://api.test/v1/images/generations"
    assert sent.get_header("Authorization") == f"Bearer {KEY}"
    assert body == {
        "model": "gpt-image-2.5-flare-2026-09-08",
        "prompt": PROMPT,
        "size": "1536x1024",
        "quality": "high",
        "n": 1,
        "output_format": "jpeg",
        "output_compression": 90,
        "moderation": "auto",
        "user": hashlib.sha256(b"membership-1").hexdigest(),
    }


def test_references_switch_to_edits_with_data_uris() -> None:
    _, opener = call(success(), references=(b"anchor-bytes",))
    sent, _ = opener.calls[0]
    body = json.loads(sent.data)

    assert sent.full_url == "https://api.test/v1/images/edits"
    assert body["images"] == [
        {"image_url": "data:image/jpeg;base64," + base64.b64encode(b"anchor-bytes").decode()}
    ]


@pytest.mark.parametrize(
    ("outcome", "kind"),
    [
        (http_error(400, "moderation_blocked"), "refused"),
        (http_error(400, "content_policy_violation"), "refused"),
        (http_error(429, "insufficient_quota", "insufficient_quota"), "quota"),
        (http_error(429, "", "billing_hard_limit_reached"), "quota"),
        (http_error(429, "rate_limit_exceeded", "requests"), "retryable"),
        (http_error(502), "retryable"),
        (http_error(503), "retryable"),
        (urllib.error.URLError(ConnectionRefusedError()), "retryable"),
        (TimeoutError(), "unknown"),
        (ConnectionResetError(), "unknown"),
        (http_error(500), "unknown"),
        (http_error(504), "unknown"),
        (http_error(401), "config"),
        (http_error(403), "config"),
        (http_error(400, "invalid_size"), "invalid"),
        (http_error(302), "invalid"),
        (FakeResponse(b"not json"), "invalid"),
        (FakeResponse(b'{"data": []}'), "invalid"),
    ],
)
def test_each_failure_maps_to_the_kind_the_caller_acts_on(outcome: Any, kind: str) -> None:
    with pytest.raises(ProviderError) as raised:
        call(outcome)

    assert raised.value.kind == kind


def test_a_timeout_while_reading_the_answer_is_unknown_not_retryable() -> None:
    class SlowResponse(FakeResponse):
        def read(self, amount: int = -1) -> bytes:
            raise TimeoutError

    with pytest.raises(ProviderError) as raised:
        call(SlowResponse(b""))

    assert raised.value.kind == "unknown"


def test_a_response_over_25_mib_is_refused_unread() -> None:
    with pytest.raises(ProviderError) as raised:
        call(FakeResponse(b"x" * (provider.RESPONSE_MAX_BYTES + 1)))

    assert raised.value.kind == "invalid"


def test_an_empty_key_is_config_and_never_opens_a_socket() -> None:
    opener = FakeOpener(success())

    with pytest.raises(ProviderError) as raised:
        generate(request(), model="m", api_key="", base_url="https://api.test/v1", opener=opener)

    assert raised.value.kind == "config"
    assert opener.calls == []


@pytest.fixture
def redirecting_server() -> Iterator[tuple[str, list[str]]]:
    hits: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            hits.append(self.path)
            self.send_response(307)
            self.send_header("Location", "/elsewhere/images/generations")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_: Any) -> None:
            return None

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", hits
    finally:
        server.shutdown()
        server.server_close()


def test_a_redirect_is_not_followed(redirecting_server: tuple[str, list[str]]) -> None:
    base_url, hits = redirecting_server

    with pytest.raises(ProviderError) as raised:
        generate(request(), model="m", api_key=KEY, base_url=base_url)

    assert raised.value.kind == "invalid"
    assert hits == ["/v1/images/generations"]


def test_neither_prompt_nor_key_reaches_logs_or_errors(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    call(success())
    with pytest.raises(ProviderError) as raised:
        call(http_error(400, "moderation_blocked"))

    for text in (caplog.text, str(raised.value), repr(raised.value), repr(request())):
        assert PROMPT not in text
        assert KEY not in text
