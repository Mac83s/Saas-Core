"""Bounded transport to the OpenAI Image API (ADR-059), stdlib only like seo/source.py.

Nothing here logs: the prompt and the key never leave this module except in the
request itself, and errors carry a code and a kind, never the payload.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from django.conf import settings

# ponytail: one direct adapter; a registry of adapters arrives with a second provider.

TIMEOUT_SECONDS = 150
RESPONSE_MAX_BYTES = 25 * 1024 * 1024
ERROR_BODY_MAX_BYTES = 64 * 1024

# GPT Image 2.5 list prices in USD per 1M tokens, i.e. micro-USD per token.
# ponytail: module constants; settings per snapshot when prices diverge between snapshots.
TEXT_INPUT_USD_PER_MTOK = 5
IMAGE_INPUT_USD_PER_MTOK = 8
IMAGE_OUTPUT_USD_PER_MTOK = 30

REFUSAL_CODES = frozenset({"moderation_blocked", "content_policy_violation"})
QUOTA_CODES = frozenset({"insufficient_quota", "billing_hard_limit_reached"})

ErrorKind = Literal["refused", "retryable", "unknown", "quota", "config", "invalid"]


class ProviderError(Exception):
    """What went wrong, as a code for the record and a kind for the caller's decision.

    - refused: moderation said no; never retried, credits released;
    - retryable: the request provably did not run (429 rate limit, 503, a
      connection that failed before the request was written); a 502 is not
      proof, since the edge answers it after an upstream that may have billed;
    - unknown: the request may have run and been paid for; never sent again;
    - quota: the spending limit is exhausted; the offer becomes unavailable;
    - config: no key, or the key was rejected;
    - invalid: anything else the adapter cannot use.
    """

    def __init__(self, code: str, kind: ErrorKind):
        self.code = code
        self.kind = kind
        super().__init__(code)


@dataclass(frozen=True, kw_only=True)
class ImageRequest:
    prompt: str = field(repr=False)
    width: int
    height: int
    quality: str = "high"
    references: tuple[bytes, ...] = field(default=(), repr=False)
    #: A stable identifier of who asked; sent to the provider only as a hash.
    end_user: str = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class GeneratedImage:
    content: bytes = field(repr=False)
    content_type: str = "image/jpeg"
    model: str
    cost_usd_micros: int
    provider_request_id: str
    usage: Mapping[str, Any] = field(default_factory=dict)


class Opener(Protocol):
    def open(self, request: urllib.request.Request, timeout: float) -> Any: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):  # type: ignore[no-untyped-def]
        return None


def generate(
    request: ImageRequest,
    *,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    opener: Opener | None = None,
) -> GeneratedImage:
    body: dict[str, Any] = {
        "model": model,
        "prompt": request.prompt,
        "size": f"{request.width}x{request.height}",
        "quality": request.quality,
        "n": 1,
        "output_format": "jpeg",
        "output_compression": 90,
        "moderation": "auto",
        "user": hashlib.sha256(request.end_user.encode()).hexdigest(),
    }
    path = "/images/generations"
    if request.references:
        path = "/images/edits"
        body["images"] = [
            {"image_url": "data:image/jpeg;base64," + base64.b64encode(image).decode()}
            for image in request.references
        ]
    payload, request_id = _post(path, body, api_key=api_key, base_url=base_url, opener=opener)
    try:
        content = base64.b64decode(payload["data"][0]["b64_json"], validate=True)
        usage = payload.get("usage") or {}
        details = usage.get("input_tokens_details") or {}
        image_input = int(details.get("image_tokens") or 0)
        text_input = int(details.get("text_tokens") or 0)
        if not details:
            text_input = int(usage.get("input_tokens") or 0)
        output = int(usage.get("output_tokens") or 0)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as error:
        raise ProviderError("openai_response_malformed", "invalid") from error
    if not content.startswith(b"\xff\xd8\xff"):
        raise ProviderError("openai_response_not_jpeg", "invalid")
    return GeneratedImage(
        content=content,
        model=model,
        cost_usd_micros=text_input * TEXT_INPUT_USD_PER_MTOK
        + image_input * IMAGE_INPUT_USD_PER_MTOK
        + output * IMAGE_OUTPUT_USD_PER_MTOK,
        provider_request_id=request_id,
        usage=usage,
    )


def check_provenance(
    content: bytes,
    *,
    content_type: str,
    api_key: str | None = None,
    base_url: str | None = None,
    opener: Opener | None = None,
) -> dict[str, Any]:
    """Ask the provider whether its C2PA manifest and SynthID survive in ``content``."""
    payload, _ = _post(
        "/content_provenance_checks",
        {"image_url": f"data:{content_type};base64," + base64.b64encode(content).decode()},
        api_key=api_key,
        base_url=base_url,
        opener=opener,
    )
    return payload


def _post(
    path: str,
    body: dict[str, Any],
    *,
    api_key: str | None,
    base_url: str | None,
    opener: Opener | None,
) -> tuple[dict[str, Any], str]:
    key = settings.IMAGE_GENERATION_OPENAI_API_KEY if api_key is None else api_key
    base = str(base_url or settings.IMAGE_GENERATION_BASE_URL).rstrip("/")
    parsed = urlsplit(base)
    if (
        not key
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ProviderError("image_generation_unconfigured", "config")
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    transport = opener or urllib.request.build_opener(_NoRedirect)
    try:
        with transport.open(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(RESPONSE_MAX_BYTES + 1)
            request_id = str(response.headers.get("x-request-id") or "")
    except urllib.error.HTTPError as error:
        raise _http_error(error) from None
    except urllib.error.URLError as error:
        # urllib wraps only what failed while connecting or writing the request.
        raise ProviderError("openai_transport_unsent", "retryable") from error
    except (TimeoutError, OSError, http.client.HTTPException) as error:
        # Sent, then the answer did not arrive: the image may have been paid for.
        raise ProviderError("openai_result_unknown", "unknown") from error
    if len(raw) > RESPONSE_MAX_BYTES:
        raise ProviderError("openai_response_too_large", "invalid")
    try:
        payload = json.loads(raw)
    except ValueError as error:
        raise ProviderError("openai_response_malformed", "invalid") from error
    if not isinstance(payload, dict):
        raise ProviderError("openai_response_malformed", "invalid")
    return payload, request_id


def _http_error(error: urllib.error.HTTPError) -> ProviderError:
    status = error.code
    code = error_type = ""
    try:
        detail = json.loads(error.read(ERROR_BODY_MAX_BYTES)).get("error") or {}
        code, error_type = str(detail.get("code") or ""), str(detail.get("type") or "")
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    finally:
        error.close()
    if status == 400 and code in REFUSAL_CODES:
        return ProviderError(code, "refused")
    # The hard spend limit arrives as 400 billing_hard_limit_reached, not 429.
    if 400 <= status < 500 and (code in QUOTA_CODES or error_type in QUOTA_CODES):
        return ProviderError(code or error_type, "quota")
    if status in {429, 503}:
        return ProviderError(f"openai_http_{status}", "retryable")
    if status in {401, 403}:
        return ProviderError(f"openai_http_{status}", "config")
    if status >= 500:
        return ProviderError(f"openai_http_{status}", "unknown")
    return ProviderError(f"openai_http_{status}", "invalid")
