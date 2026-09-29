"""Text to vectors for meaning-based catalogue search (ADR-064 §8).

The backend asks the provider, not the engine: the engine stays without
internet and without the key, and a test replaces this module's `_post`.
OpenRouter by default (the owner's answer of 29.09), whose `/embeddings` speaks
the OpenAI format, so another OpenAI-compatible provider is a setting.

Vectors are cut to `CATALOG_EMBEDDING_DIMENSIONS` and normalised here. The
default model (Qwen3-Embedding) is trained for such cuts; a model that is not
needs the setting equal to its own size.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0
QUERY_TIMEOUT_SECONDS = 2.0
BATCH = 32
#: Same query, same vector: a repeated search costs no provider call.
QUERY_CACHE_SECONDS = 30 * 24 * 3600
#: Qwen3-Embedding wants the task said before a query, never before a document.
QUERY_INSTRUCTION = (
    "Instruct: Given a search typed into a local business directory, retrieve "
    "the businesses that offer what it asks for\nQuery: "
)


class EmbeddingUnavailable(Exception):
    """No key, no answer, or an answer that is not a list of vectors."""


def configured() -> bool:
    return bool(settings.CATALOG_EMBEDDING_API_KEY)


def model() -> str:
    """What produced the vectors in the index; a change makes them all stale."""
    return f"{settings.CATALOG_EMBEDDING_MODEL}@{settings.CATALOG_EMBEDDING_DIMENSIONS}"


def _post(body: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        settings.CATALOG_EMBEDDING_BASE_URL.rstrip("/") + "/embeddings",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {settings.CATALOG_EMBEDDING_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload: dict[str, Any] = json.loads(response.read())
            return payload
    except urllib.error.HTTPError as error:
        raise EmbeddingUnavailable(f"embedding_http_{error.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise EmbeddingUnavailable("embedding_unreachable") from error


def _normalised(vector: list[float]) -> list[float]:
    cut = vector[: settings.CATALOG_EMBEDDING_DIMENSIONS]
    length = math.sqrt(sum(value * value for value in cut)) or 1.0
    return [value / length for value in cut]


def _embed(texts: list[str], timeout: float) -> list[list[float]]:
    if not configured():
        raise EmbeddingUnavailable("embedding_unconfigured")
    payload = _post(
        {
            "model": settings.CATALOG_EMBEDDING_MODEL,
            "input": texts,
            "encoding_format": "float",
            # Public text either way, but nobody's training set.
            "provider": {"data_collection": "deny"},
        },
        timeout,
    )
    try:
        rows = sorted(payload["data"], key=lambda row: row["index"])
        vectors = [_normalised([float(value) for value in row["embedding"]]) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        raise EmbeddingUnavailable("embedding_response_malformed") from error
    if len(vectors) != len(texts) or any(
        len(vector) != settings.CATALOG_EMBEDDING_DIMENSIONS for vector in vectors
    ):
        raise EmbeddingUnavailable("embedding_response_malformed")
    return vectors


def embed_documents(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH):
        vectors.extend(_embed(texts[start : start + BATCH], TIMEOUT_SECONDS))
    return vectors


def embed_query(text: str) -> list[float]:
    key = "catalog-query-vector:" + hashlib.sha256(f"{model()}\n{text}".encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return list(cached)
    vector = _embed([QUERY_INSTRUCTION + text], QUERY_TIMEOUT_SECONDS)[0]
    cache.set(key, vector, QUERY_CACHE_SECONDS)
    return vector
