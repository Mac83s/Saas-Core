"""What a content module implements to have its content translated (§6 of
docs/architecture/translation-sources.md).

The module owns the content: it lists objects, reads units with the targets
realigned to the current structure, writes results through its own services
(locks, audit, idempotency, its write gate), publishes its own way and takes a
person's review. The engine only translates. Every type here is plain data;
the context is a Protocol `TenantContext` satisfies as it is.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from .policy import PublicationFacts, Trigger, WriteTarget
from .provenance import Provenance
from .units import ProtectedMode, Target, Unit

type Basis = Literal["published", "working"]
type Staging = Literal["live_record", "versioned"]
type SourceAction = Literal["read", "translate", "publish", "withdraw"]
type ReviewAction = Literal["accept", "discard", "withdraw"]
type OutcomeState = Literal["live", "pending", "draft", "conflict", "refused"]
type ProtectedRule = Literal["keep", "name"]

BASES = frozenset({"published", "working"})
STAGINGS = frozenset({"live_record", "versioned"})

# Why a read leaves an object out.
EXCLUDED_DELETED = "deleted"
EXCLUDED_WITHDRAWN = "withdrawn"
EXCLUDED_SOURCE_UNPUBLISHED = "source_unpublished"
EXCLUDED_LOCALE_IS_SOURCE = "locale_is_source"
EXCLUDED_LOCALE_NOT_ENABLED = "locale_not_enabled"

# Write outcome reasons a module adds to the policy's (`policy.REASON_*`).
CONFLICT_SOURCE_CHANGED = "source_changed"
CONFLICT_TARGET_CHANGED = "target_changed"
CONFLICT_IDEMPOTENCY = "idempotency_conflict"
PERSON_REQUIRED = "person_required"

LIST_LIMIT = 200


class ContentContext(Protocol):
    """`TenantContext` fits as it is (ADR-076 §6 for `acting_*`)."""

    @property
    def organization_id(self) -> UUID: ...
    @property
    def membership_id(self) -> UUID | None: ...
    @property
    def actor_id(self) -> UUID | None: ...
    @property
    def principal_kind(self) -> str: ...
    @property
    def credential_id(self) -> UUID | None: ...
    @property
    def acting_via(self) -> str: ...
    @property
    def acting_ref(self) -> str: ...
    @property
    def acting_trigger(self) -> str: ...

    def has_permission(self, permission: str, /) -> bool: ...


@dataclass(frozen=True, slots=True)
class FieldError:
    """The A1a validation error shape; `field` is `units.<key>` here."""

    field: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ObjectRef:
    object_id: UUID
    # Customer text: data, never an instruction.
    label: str
    # The publication scope, e.g. the site.
    scope: str
    # 0 goes first (a site's home page).
    priority: int
    # Has a public surface now; automation plans only these.
    public: bool
    # Opaque version tokens, compared for equality only.
    published_version: str | None
    working_version: str | None
    changed_at: datetime


@dataclass(frozen=True, slots=True)
class ObjectPage:
    items: tuple[ObjectRef, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class SourceRead:
    object_id: UUID
    locale: str
    basis: Basis
    scope: str
    source_locale: str
    # Opaque: the source version the units come from.
    basis_version: str
    # Opaque: the target version the targets come from.
    target_version: str | None
    units: tuple[Unit, ...]
    # By unit key, realigned to this structure; a removed unit's target is absent.
    targets: Mapping[str, Target]
    facts: PublicationFacts
    # `EXCLUDED_*` when the object cannot be translated into this locale now.
    excluded: str | None = None


@dataclass(frozen=True, slots=True)
class WriteItem:
    object_id: UUID
    locale: str
    basis: Basis
    basis_version: str
    target_version: str | None
    # Delivered texts by unit key, past the engine's hard checks.
    texts: Mapping[str, tuple[str, Provenance]]
    requested: WriteTarget
    # E.g. `qa_flagged` when `requested` is "pending".
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class WriteBatch:
    source_key: str
    scope: str
    trigger: Trigger
    protected: ProtectedMode
    # In priority order.
    items: tuple[WriteItem, ...]
    # Stable per (job, batch, scope).
    idempotency_key: str
    published_in_job: frozenset[UUID] = frozenset()


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    object_id: UUID
    locale: str
    state: OutcomeState
    # One item may give two outcomes: what went out and what waits.
    keys: tuple[str, ...]
    reason: str | None = None
    errors: tuple[FieldError, ...] = ()
    target_version: str | None = None


@dataclass(frozen=True, slots=True)
class Completeness:
    # Every required unit has a translation (fresh, stale, unverified, copied).
    complete: bool
    # Complete and passing the module's own rules.
    publishable: bool
    untranslated: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewItem:
    object_id: UUID
    locale: str
    expected_version: str | None


@dataclass(frozen=True, slots=True)
class ProtectedTerm:
    text: str
    rule: ProtectedRule


class TranslationSource(Protocol):
    key: str
    # Gated per organization type.
    module_id: str
    # {"pl": ..., "en": ...}
    labels: Mapping[str, str]
    staging: Staging
    bases: frozenset[str]
    write_targets: frozenset[str]
    translations_publish_separately: bool

    def authorize(
        self, *, context: ContentContext, action: SourceAction, object_ids: Sequence[UUID]
    ) -> None: ...

    def list_objects(
        self,
        *,
        context: ContentContext,
        cursor: str | None,
        limit: int,
        changed_since: datetime | None = None,
    ) -> ObjectPage: ...

    def read(
        self, *, context: ContentContext, object_id: UUID, locale: str, basis: Basis
    ) -> SourceRead: ...

    def write(self, *, context: ContentContext, batch: WriteBatch) -> tuple[WriteOutcome, ...]: ...

    # The publication id; nothing for a live record.
    def publish(
        self, *, context: ContentContext, scope: str, job_ref: str, idempotency_key: str
    ) -> str | None: ...

    def completeness(
        self, *, context: ContentContext, object_id: UUID, locale: str
    ) -> Completeness: ...

    def protected_terms(
        self, *, context: ContentContext, object_id: UUID
    ) -> tuple[ProtectedTerm, ...]: ...

    def review(
        self,
        *,
        context: ContentContext,
        action: ReviewAction,
        items: Sequence[ReviewItem],
        idempotency_key: str,
    ) -> tuple[WriteOutcome, ...]: ...

    def revert(
        self, *, context: ContentContext, job_ref: str, idempotency_key: str
    ) -> tuple[WriteOutcome, ...]: ...
