"""The booking catalogue as a translation source: `booking.catalog` (ADR-069;
plan TL12c; docs/architecture/translation-sources.md §10).

One object per company — its booking catalogue, under the company's id — so
a burst of changes is one demand and one job. Its units are each item's
fields, keyed `<kind>/<item id>/<field>` and ordered by kind and name: every
service, place, unit and group of units the company offers (switched-off ones
are not offered, so they have no units), and its teams. A team's name is a
proper name: a `name` unit, never sent to a model unasked. People are never
units. A new kind of item joins with `register_translatable`.

A live record: the public form reads what is written at once, a result for a
person waits in the engine's review queue. Writes go through
`apply_item_translation`, item by item (version, history); a receipt per
(language, key) answers a repeat and keeps the replaced texts for `revert`.
Nothing here imports the translation engine.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from rest_framework.exceptions import NotFound, PermissionDenied

from saas_core.content_protocol import registry
from saas_core.content_protocol.policy import (
    REASON_GATE_FAILED,
    REASON_OVERWRITES_HUMAN,
    PublicationFacts,
    decide_publication,
)
from saas_core.content_protocol.provenance import ORIGIN_COPY, ORIGIN_HUMAN, Provenance
from saas_core.content_protocol.sources import (
    CONFLICT_IDEMPOTENCY,
    CONFLICT_SOURCE_CHANGED,
    CONFLICT_TARGET_CHANGED,
    EXCLUDED_LOCALE_IS_SOURCE,
    EXCLUDED_LOCALE_NOT_ENABLED,
    Basis,
    Completeness,
    ContentContext,
    FieldError,
    ObjectPage,
    ObjectRef,
    OutcomeState,
    ProtectedTerm,
    ReviewAction,
    ReviewItem,
    SourceAction,
    SourceRead,
    Staging,
    WriteBatch,
    WriteItem,
    WriteOutcome,
)
from saas_core.content_protocol.tokens import PLACEHOLDER_PATTERN
from saas_core.content_protocol.units import Target, Unit, unit_state
from saas_core.content_protocol.writes import (
    GATE_UNKNOWN_UNIT,
    item_digest,
    outcome_from_dict,
    outcome_to_dict,
    write_gate,
)
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.locales import organization_content_locales
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.person_gate import assert_person_required

from .item_translations import (
    LEGACY_SOURCE,
    Translatable,
    apply_item_translation,
    item_units,
    row_targets,
    source_locale,
    translatables,
)
from .models import CatalogTranslationWrite, PublicBookingRoute
from .services import BOOKING_MANAGE

SOURCE_KEY = "booking.catalog"
#: A person's decision on a translation (the label pages, articles and cards use).
REVIEW_GATE = "Decyzja o tłumaczeniu AI"


@contextmanager
def _tenant(context: ContentContext) -> Iterator[None]:
    if not isinstance(context, TenantContext):
        raise TypeError("A booking translation call needs a tenant context.")
    with transaction.atomic():
        set_local_organization_id(context.organization_id)
        with activate_tenant_context(context):
            yield


def _items(entry: Translatable, organization_id: UUID) -> list[Any]:
    """What the company offers of a kind: a switched-off item is not offered."""
    rows = entry.model.all_objects.filter(organization_id=organization_id)  # type: ignore[attr-defined]
    if any(field.name == "active" for field in entry.model._meta.fields):
        rows = rows.filter(active=True)
    return sorted(rows, key=lambda item: (str(getattr(item, "name", "")).lower(), str(item.id)))


def unit_key(entry: Translatable, item: Any, field: str) -> str:
    return f"{entry.kind}/{item.id}/{field}"


def split_key(key: str) -> tuple[str, UUID, str] | None:
    parts = key.split("/")
    if len(parts) != 3:
        return None
    try:
        return parts[0], UUID(parts[1]), parts[2]
    except ValueError:
        return None


def catalog(organization_id: UUID) -> list[tuple[Translatable, Any, Unit]]:
    """Every unit of the company's catalogue with its item, in order."""
    found = []
    for entry in translatables():
        for item in _items(entry, organization_id):
            for unit in item_units(entry, item):
                keyed = replace(
                    unit,
                    key=unit_key(entry, item, unit.key),
                    placeholder=PLACEHOLDER_PATTERN.search(unit.text) is not None,
                )
                found.append((entry, item, keyed))
    return found


def _rows(entry: Translatable, organization_id: UUID, locale: str) -> dict[UUID, Any]:
    rows = entry.translation.all_objects.filter(
        organization_id=organization_id, locale=locale
    )
    return {getattr(row, f"{entry.relation}_id"): row for row in rows}


def catalog_targets(
    organization_id: UUID, locale: str, units: Sequence[tuple[Translatable, Any, Unit]]
) -> dict[str, Target]:
    rows = {entry.kind: _rows(entry, organization_id, locale) for entry in translatables()}
    targets: dict[str, Target] = {}
    for entry, item, unit in units:
        field = unit.key.rsplit("/", 1)[1]
        row = rows[entry.kind].get(item.id)
        found = row_targets(row, [replace(unit, key=field)]).get(field)
        if found is not None:
            targets[unit.key] = found
    return targets


def _digest(values: Sequence[Any]) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:16]


def basis_version(units: Sequence[tuple[Translatable, Any, Unit]]) -> str:
    return "catalog:" + _digest([[unit.key, unit.source_hash] for _e, _i, unit in units])


def target_version(organization_id: UUID, locale: str) -> str:
    versions = sorted(
        [entry.kind, str(item_id), row.version]
        for entry in translatables()
        for item_id, row in _rows(entry, organization_id, locale).items()
    )
    return _digest(versions) if versions else "0"


def _speaks(organization_id: UUID, locale: str) -> bool:
    """The company's booking catalogue already has this language somewhere
    (not counting the source's own text standing in)."""
    for entry in translatables():
        for row in _rows(entry, organization_id, locale).values():
            for field, text in (row.texts or {}).items():
                origin = (row.provenance or {}).get(field) or {}
                if text and origin.get("origin") != ORIGIN_COPY:
                    return True
    return False


def _facts(context: ContentContext, organization_id: UUID, locale: str) -> PublicationFacts:
    speaks = _speaks(organization_id, locale)
    return PublicationFacts(
        legal_document=False,
        locale_live=speaks,
        actor_may_publish=context.has_permission(BOOKING_MANAGE),
        target_public=speaks,
    )


def _own(context: ContentContext, object_id: UUID) -> UUID:
    if object_id != context.organization_id:
        raise NotFound("Nie ma takiego katalogu.")
    return object_id


class BookingCatalogSource:
    key = SOURCE_KEY
    module_id = "shared.booking"
    labels: Mapping[str, str] = {"pl": "Katalog rezerwacji", "en": "Booking catalogue"}
    staging: Staging = "live_record"
    bases = frozenset({"published"})
    write_targets = frozenset({"live"})
    translations_publish_separately = False

    def authorize(
        self, *, context: ContentContext, action: SourceAction, object_ids: Sequence[UUID]
    ) -> None:
        # Reading and translating need membership; publishing the result is
        # the catalogue's manager's (a translation by anybody else waits).
        if action in ("publish", "withdraw") and not context.has_permission(BOOKING_MANAGE):
            raise PermissionDenied("Brak uprawnienia do katalogu rezerwacji.")
        for object_id in object_ids:
            _own(context, object_id)

    def list_objects(
        self,
        *,
        context: ContentContext,
        cursor: str | None,
        limit: int,
        changed_since: datetime | None = None,
    ) -> ObjectPage:
        with _tenant(context):
            organization_id = context.organization_id
            units = catalog(organization_id)
            if cursor or not units:
                return ObjectPage(items=(), next_cursor=None)
            changed_at = max(
                getattr(item, "updated_at", None) or item.created_at
                for _entry, item, _unit in units
            )
            if changed_since is not None and changed_at < changed_since:
                return ObjectPage(items=(), next_cursor=None)
            organization = Organization.objects.get(pk=organization_id)
            version = basis_version(units)
            return ObjectPage(
                items=(
                    ObjectRef(
                        object_id=organization_id,
                        label=organization.name,
                        scope=str(organization_id),
                        priority=3,
                        public=PublicBookingRoute.objects.filter(
                            organization_id=organization_id, active=True
                        ).exists(),
                        published_version=version,
                        working_version=version,
                        changed_at=changed_at,
                    ),
                ),
                next_cursor=None,
            )

    def read(
        self, *, context: ContentContext, object_id: UUID, locale: str, basis: Basis
    ) -> SourceRead:
        if basis not in self.bases:
            raise ValueError(f"Source {self.key} has no {basis!r} basis.")
        with _tenant(context):
            organization_id = _own(context, object_id)
            organization = Organization.objects.get(pk=organization_id)
            own = source_locale(organization)
            excluded = None
            if locale == own:
                excluded = EXCLUDED_LOCALE_IS_SOURCE
            elif locale not in organization_content_locales(organization):
                excluded = EXCLUDED_LOCALE_NOT_ENABLED
            units = catalog(organization_id)
            shown = () if excluded else tuple(unit for _e, _i, unit in units)
            return SourceRead(
                object_id=organization_id,
                locale=locale,
                basis="published",
                scope=str(organization_id),
                source_locale=own,
                basis_version=basis_version(units),
                target_version=target_version(organization_id, locale),
                units=shown,
                targets=catalog_targets(organization_id, locale, units) if shown else {},
                facts=_facts(context, organization_id, locale),
                excluded=excluded,
            )

    def write(self, *, context: ContentContext, batch: WriteBatch) -> tuple[WriteOutcome, ...]:
        if batch.source_key != self.key:
            raise ValueError("The batch is for another source.")
        self.authorize(
            context=context, action="translate", object_ids=[i.object_id for i in batch.items]
        )
        with _tenant(context):
            published_now = set(batch.published_in_job)
            outcomes: list[WriteOutcome] = []
            for item in batch.items:
                outcomes.extend(self._write_item(context, batch, item, published_now))
            return tuple(outcomes)

    def _write_item(
        self,
        context: ContentContext,
        batch: WriteBatch,
        item: WriteItem,
        published_now: set[UUID],
    ) -> tuple[WriteOutcome, ...]:
        organization_id = _own(context, item.object_id)
        keys = tuple(sorted(item.texts))

        def outcome(
            state: OutcomeState, chosen: Sequence[str], reason: str | None, **extra: Any
        ) -> WriteOutcome:
            return WriteOutcome(
                object_id=organization_id,
                locale=item.locale,
                state=state,
                keys=tuple(sorted(chosen)),
                reason=reason,
                **extra,
            )

        digest = item_digest(item)
        seen = CatalogTranslationWrite.all_objects.filter(
            organization_id=organization_id,
            locale=item.locale,
            idempotency_key=batch.idempotency_key[:64],
        ).first()
        if seen is not None:
            if seen.request_hash == digest:
                return tuple(outcome_from_dict(stored) for stored in seen.outcomes)
            return (outcome("conflict", keys, CONFLICT_IDEMPOTENCY),)
        units = catalog(organization_id)
        if item.basis_version != basis_version(units):
            return (outcome("conflict", keys, CONFLICT_SOURCE_CHANGED),)
        if item.target_version != target_version(organization_id, item.locale):
            return (outcome("conflict", keys, CONFLICT_TARGET_CHANGED),)
        facts = replace(
            _facts(context, organization_id, item.locale),
            object_published_in_job=organization_id in published_now,
            published_in_job=len(published_now - {organization_id}),
        )
        decision = decide_publication(
            policy=registry.translation_policy(organization_id=context.organization_id),
            requested=item.requested,
            requested_reason=item.reason,
            trigger=batch.trigger,
            facts=facts,
        )
        if decision.outcome == "refused":
            return self._receipt(
                organization_id,
                batch,
                item,
                digest,
                (outcome("refused", keys, decision.reason),),
                {},
            )
        by_key = {unit.key: (entry, it, unit) for entry, it, unit in units}
        current = catalog_targets(organization_id, item.locale, units)
        terms = self.protected_terms(context=context, object_id=organization_id)
        written: dict[str, tuple[str, Provenance]] = {}
        proposals: list[str] = []
        errors: list[FieldError] = []
        for key, (text, provenance) in item.texts.items():
            found = by_key.get(key)
            if found is None:
                errors.append(FieldError(f"units.{key}", GATE_UNKNOWN_UNIT, "No such unit."))
                continue
            error = write_gate(found[2], text, terms)
            if error is not None:
                errors.append(error)
                continue
            if batch.protected != "overwrite" and unit_state(found[2], current.get(key)).protected:
                proposals.append(key)
            else:
                written[key] = (text, provenance)
        results: list[WriteOutcome] = []
        replaced: dict[str, Any] = {}
        if written:
            state: OutcomeState = decision.outcome
            if state == "live":
                replaced = _apply(organization_id, item.locale, written, by_key, context.actor_id)
                published_now.add(organization_id)
            results.append(
                outcome(
                    state,
                    list(written),
                    decision.reason,
                    target_version=target_version(organization_id, item.locale),
                )
            )
        if proposals:
            results.append(outcome("pending", proposals, REASON_OVERWRITES_HUMAN))
        if errors:
            results.append(
                outcome(
                    "pending",
                    [error.field.removeprefix("units.") for error in errors],
                    REASON_GATE_FAILED,
                    errors=tuple(errors),
                )
            )
        return self._receipt(organization_id, batch, item, digest, tuple(results), replaced)

    @staticmethod
    def _receipt(
        organization_id: UUID,
        batch: WriteBatch,
        item: WriteItem,
        digest: str,
        outcomes: tuple[WriteOutcome, ...],
        replaced: dict[str, Any],
    ) -> tuple[WriteOutcome, ...]:
        CatalogTranslationWrite.all_objects.create(
            organization_id=organization_id,
            locale=item.locale,
            idempotency_key=batch.idempotency_key[:64],
            request_hash=digest,
            job_ref=batch.trigger.job_ref or "",
            outcomes=[outcome_to_dict(outcome) for outcome in outcomes],
            replaced=replaced,
        )
        return outcomes

    def publish(
        self, *, context: ContentContext, scope: str, job_ref: str, idempotency_key: str
    ) -> str | None:
        return None  # A live record went out with the write.

    def completeness(
        self, *, context: ContentContext, object_id: UUID, locale: str
    ) -> Completeness:
        with _tenant(context):
            organization_id = _own(context, object_id)
            units = catalog(organization_id)
            targets = catalog_targets(organization_id, locale, units)
            untranslated = tuple(
                unit.key
                for _e, _i, unit in units
                if unit.required
                and unit_state(unit, targets.get(unit.key)).status in ("missing", "blocked")
            )
            return Completeness(
                complete=not untranslated,
                publishable=not untranslated,
                untranslated=untranslated,
                reasons=("untranslated_units",) if untranslated else (),
            )

    def protected_terms(
        self, *, context: ContentContext, object_id: UUID
    ) -> tuple[ProtectedTerm, ...]:
        """The company's own name, kept as written."""
        organization = Organization.objects.filter(pk=context.organization_id).first()
        if organization is None or not organization.name.strip():
            return ()
        return (ProtectedTerm(text=organization.name.strip(), rule="keep"),)

    def review(
        self,
        *,
        context: ContentContext,
        action: ReviewAction,
        items: Sequence[ReviewItem],
        idempotency_key: str,
    ) -> tuple[WriteOutcome, ...]:
        """A person's decision. Accepting a live record is the engine's write;
        withdrawing takes the catalogue's language down."""
        with _tenant(context):
            assert_person_required(context, REVIEW_GATE)  # type: ignore[arg-type]
        self.authorize(context=context, action="publish", object_ids=[i.object_id for i in items])
        if action != "withdraw":
            return ()
        outcomes: list[WriteOutcome] = []
        with _tenant(context):
            for review in items:
                organization_id = _own(context, review.object_id)
                units = catalog(organization_id)
                targets = catalog_targets(organization_id, review.locale, units)
                blank = Provenance(ORIGIN_HUMAN, LEGACY_SOURCE)
                by_key = {unit.key: (entry, it, unit) for entry, it, unit in units}
                _apply(
                    organization_id,
                    review.locale,
                    {key: ("", blank) for key in targets},
                    by_key,
                    context.actor_id,
                )
                outcomes.append(
                    WriteOutcome(
                        organization_id, review.locale, "draft", keys=(), reason="withdrawn"
                    )
                )
        return tuple(outcomes)

    def revert(
        self, *, context: ContentContext, job_ref: str, idempotency_key: str
    ) -> tuple[WriteOutcome, ...]:
        """Puts back what each of the job's writes replaced, newest first."""
        touched: list[tuple[UUID, str]] = []
        with _tenant(context):
            organization_id = context.organization_id
            receipts = CatalogTranslationWrite.all_objects.filter(
                organization_id=organization_id, job_ref=job_ref
            ).order_by("-created_at")
            units = catalog(organization_id)
            by_key = {unit.key: (entry, it, unit) for entry, it, unit in units}
            for receipt in receipts:
                if not receipt.replaced:
                    continue
                previous: dict[str, tuple[str, Provenance]] = {}
                for key, value in receipt.replaced.items():
                    if value is None:
                        previous[key] = ("", Provenance(ORIGIN_HUMAN, LEGACY_SOURCE))
                    else:
                        previous[key] = (str(value[0]), Provenance.from_dict(dict(value[1])))
                _apply(organization_id, receipt.locale, previous, by_key, context.actor_id)
                receipt.replaced = {}
                receipt.save(update_fields=["replaced"])
                if (organization_id, receipt.locale) not in touched:
                    touched.append((organization_id, receipt.locale))
        return tuple(
            WriteOutcome(object_id, locale, "live", keys=(), reason=None)
            for object_id, locale in touched
        )


def _apply(
    organization_id: UUID,
    locale: str,
    texts: Mapping[str, tuple[str, Provenance]],
    by_key: Mapping[str, tuple[Translatable, Any, Unit]],
    actor_id: UUID | None,
) -> dict[str, Any]:
    """Writes the texts item by item; returns what each unit held before."""
    grouped: dict[
        tuple[str, UUID], tuple[Translatable, Any, dict[str, tuple[str, Provenance]]]
    ] = {}
    for key, value in texts.items():
        found = by_key.get(key)
        if found is None:
            continue
        entry, item, _unit = found
        field = key.rsplit("/", 1)[1]
        grouped.setdefault((entry.kind, item.id), (entry, item, {}))[2][field] = value
    replaced: dict[str, Any] = {}
    for entry, item, fields in grouped.values():
        _row, before = apply_item_translation(entry, item, locale, fields, actor_id=actor_id)
        for field, value in before.items():
            replaced[unit_key(entry, item, field)] = value
    return replaced


CATALOG_SOURCE = BookingCatalogSource()


def register_catalog_source() -> None:
    registry.register_translation_source(CATALOG_SOURCE)


def notify_catalog_changed(*, context: Any, change: str = "changed") -> None:
    """The company's booking catalogue changed a name, a description, or what
    it offers, in the transaction that changed it (§8.1)."""
    registry.notify_source_changed(
        context=context,
        source_key=SOURCE_KEY,
        object_ids=[context.organization_id],
        change=change,  # type: ignore[arg-type]
        cause="api_key" if getattr(context, "principal_kind", "") == "api_key" else "user",
    )
