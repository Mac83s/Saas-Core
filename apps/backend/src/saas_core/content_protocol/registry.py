"""Where content modules and the translation engine meet (ADR-069 pkt 2, 4).

Modules register their sources from `AppConfig.ready`; the engine registers
the policy and listens for source changes. Without the engine the policy is
`POLICY_OFF` and a change notice goes nowhere, so manual translation keeps
working in a profile that does not compose it.

A declaration is checked when it is registered: a broken adapter stops the
start, not a customer's job.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from .policy import POLICY_OFF, WRITE_TARGETS, TranslationPolicy
from .sources import BASES, STAGINGS, ContentContext, TranslationSource

type SourceChange = Literal["changed", "withdrawn", "deleted"]

SOURCE_CHANGES = frozenset({"changed", "withdrawn", "deleted"})
TESTING_PREFIX = "testing."
LABEL_LOCALES = ("pl", "en")

_KEY = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*")

logger = logging.getLogger("saas_core.content_protocol")


class TranslationRegistryError(RuntimeError):
    """Raised from `AppConfig.ready`: stops the start."""


class TranslationPolicyProvider(Protocol):
    def policy(self, *, organization_id: UUID) -> TranslationPolicy: ...


@dataclass(frozen=True, slots=True)
class SourceChangeNotice:
    organization_id: UUID
    source_key: str
    object_ids: tuple[UUID, ...]
    change: str
    # user | api_key | schedule
    cause: str
    actor_id: UUID | None
    at: datetime


@dataclass(frozen=True, slots=True)
class WaitingReview:
    """A result a person can accept now, at the version a decision names."""

    id: UUID
    version: int
    # The waiting text is kept by the engine alone (a live record): it is read
    # in the review's own comparison before the decision.
    comparable: bool = False


#: (source key, object, language) → what waits there for a person's decision.
type WaitingReviews = Mapping[tuple[str, UUID, str], WaitingReview]

_sources: dict[str, TranslationSource] = {}
_policy: list[TranslationPolicyProvider] = []
_listeners: list[Callable[[SourceChangeNotice], None]] = []
_review_readers: list[Callable[[ContentContext], WaitingReviews]] = []
_review_closers: list[Callable[[ContentContext, str, UUID, str], None]] = []


def register_translation_source(source: TranslationSource, *, _testing: bool = False) -> None:
    """Registers a module's source; the same object again is a no-op."""
    key = source.key
    if key.startswith(TESTING_PREFIX) != _testing:
        raise TranslationRegistryError(
            f"Source {key!r}: the `testing.` prefix is for test sources only, and only there."
        )
    registered = _sources.get(key)
    if registered is source:
        return
    if registered is not None:
        raise TranslationRegistryError(f"Source {key!r} is already registered by another object.")
    _check_declaration(source)
    _sources[key] = source


def unregister_translation_source(key: str) -> None:
    """For test helpers only (`saas_core.testing.translation_sources`)."""
    _sources.pop(key, None)


def _check_declaration(source: TranslationSource) -> None:
    key = source.key
    if not _KEY.fullmatch(key):
        raise TranslationRegistryError(f"Source key {key!r} must be `<app label>.<thing>`.")
    if not source.module_id:
        raise TranslationRegistryError(f"Source {key!r} names no module.")
    for locale in LABEL_LOCALES:
        if not str(source.labels.get(locale, "")).strip():
            raise TranslationRegistryError(f"Source {key!r} has no {locale!r} label.")
    if source.staging not in STAGINGS:
        raise TranslationRegistryError(f"Source {key!r}: unknown staging {source.staging!r}.")
    bases, targets = frozenset(source.bases), frozenset(source.write_targets)
    if not bases <= BASES or "published" not in bases:
        raise TranslationRegistryError(f"Source {key!r}: bases must include `published`.")
    if not targets <= WRITE_TARGETS:
        raise TranslationRegistryError(f"Source {key!r}: unknown write targets.")
    if source.staging == "live_record":
        if bases != {"published"} or targets != {"live"}:
            raise TranslationRegistryError(
                f"Source {key!r}: a live record has only the `published` basis and `live` writes."
            )
        return
    if not {"pending", "live"} <= targets:
        raise TranslationRegistryError(
            f"Source {key!r}: a versioned source writes at least `pending` and `live`."
        )
    if ("draft" in targets) != ("working" in bases):
        raise TranslationRegistryError(
            f"Source {key!r}: `draft` writes if and only if the `working` basis exists."
        )


def translation_source(key: str) -> TranslationSource:
    try:
        return _sources[key]
    except KeyError:
        raise LookupError(f"No translation source {key!r}.") from None


def translation_sources() -> tuple[TranslationSource, ...]:
    return tuple(_sources[key] for key in sorted(_sources))


def register_translation_policy(provider: TranslationPolicyProvider) -> None:
    """The engine, once; the same object again is a no-op."""
    if _policy and _policy[0] is not provider:
        raise TranslationRegistryError("A translation policy is already registered.")
    if not _policy:
        _policy.append(provider)


def replace_translation_policy(
    provider: TranslationPolicyProvider | None,
) -> TranslationPolicyProvider | None:
    """For test helpers only: swaps the provider and returns the previous one."""
    previous = _policy[0] if _policy else None
    _policy.clear()
    if provider is not None:
        _policy.append(provider)
    return previous


def translation_policy(*, organization_id: UUID) -> TranslationPolicy:
    if not _policy:
        return POLICY_OFF
    return _policy[0].policy(organization_id=organization_id)


def register_source_change_listener(listener: Callable[[SourceChangeNotice], None]) -> None:
    if listener not in _listeners:
        _listeners.append(listener)


def unregister_source_change_listener(listener: Callable[[SourceChangeNotice], None]) -> None:
    """For test helpers only."""
    if listener in _listeners:
        _listeners.remove(listener)


def source_change_listeners() -> tuple[Callable[[SourceChangeNotice], None], ...]:
    """For test helpers only: who hears a notice now (the engine, once installed)."""
    return tuple(_listeners)


def register_review_reader(reader: Callable[[ContentContext], WaitingReviews]) -> None:
    """The engine, once: how a module's own list learns what waits for a
    person in the engine's review queue without importing the engine."""
    if reader not in _review_readers:
        _review_readers.append(reader)


def waiting_reviews(context: ContentContext) -> dict[tuple[str, UUID, str], WaitingReview]:
    """What this person can accept now, by (source key, object, language).
    Empty without the engine, or when the queue is not this person's to read."""
    found: dict[tuple[str, UUID, str], WaitingReview] = {}
    for reader in _review_readers:
        found.update(reader(context))
    return found


def register_review_closer(closer: Callable[[ContentContext, str, UUID, str], None]) -> None:
    """The engine, once: how it learns that a person decided a waiting result
    in the module's own editor, past the review queue."""
    if closer not in _review_closers:
        _review_closers.append(closer)


def review_decided(
    *, context: ContentContext, source_key: str, object_id: UUID, locale: str
) -> None:
    """A module's own decision on what waited for (object, language) — its
    editor's „Zaakceptuj” or „Odrzuć” — in the transaction that made it: the
    queue's item for the pair is moot and must not wait on. Nothing without
    the engine."""
    for closer in _review_closers:
        closer(context, source_key, object_id, locale)


def notify_source_changed(
    *,
    context: ContentContext,
    source_key: str,
    object_ids: Iterable[UUID],
    change: SourceChange = "changed",
    cause: str,
) -> None:
    """A module's public source text changed, in the transaction that changed it.

    Runs no query and never raises: a bad argument or a failing listener is a
    log line without content, never a failed save of the company's work.
    """
    if not _listeners:
        return
    try:
        ids = tuple(object_ids)
        if (
            source_key not in _sources
            or change not in SOURCE_CHANGES
            or not cause
            or not ids
            or not all(isinstance(object_id, UUID) for object_id in ids)
        ):
            logger.warning(
                "translation_source_change_rejected",
                extra={"source_key": source_key, "change": change},
            )
            return
        notice = SourceChangeNotice(
            organization_id=context.organization_id,
            source_key=source_key,
            object_ids=ids,
            change=change,
            cause=cause,
            actor_id=context.actor_id,
            at=datetime.now(UTC),
        )
    except Exception:
        logger.warning("translation_source_change_rejected", extra={"source_key": source_key})
        return
    for listener in tuple(_listeners):
        try:
            listener(notice)
        except Exception:
            logger.exception(
                "translation_source_change_failed",
                extra={"source_key": source_key, "change": change, "objects": len(ids)},
            )
