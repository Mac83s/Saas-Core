"""Business cards as a translation source: `profiles.public_profile` (ADR-069;
plan TL12a; docs/architecture/translation-sources.md §10).

A card is a live record: what is saved is public, so a translation write goes
out at once and nothing waits in the card — a result for a person waits in the
engine's review queue, and accepting it is a write (§6.3, §6.6).

- **Objects** are the company's card and its people's cards; their scope is
  the company, so a language its cards already speak is live for every card.
- **Units** are the headline, the bio and each link's label, keyed by the
  link's address (`link/<sha256(url)[:12]>`) so reordering keeps translations.
  The name, the contact details and the city are never units; the name is a
  protected term. A company's card is `public`, a person's `public_personal`:
  it reaches a model only where the deployment lists that class.
- **Targets** are the language's `PublicProfileTranslation` row, with
  provenance per unit. A text written before provenance counts as a person's,
  translating an unknown source: protected and stale.
- **Writes** go through `apply_translation` (version, audit, catalogue
  refresh); a receipt per (card, language, key) answers a repeat and keeps the
  replaced texts for `revert`.
"""

from __future__ import annotations

import hashlib
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
from saas_core.content_protocol.provenance import ORIGIN_HUMAN, Provenance
from saas_core.content_protocol.sources import (
    CONFLICT_IDEMPOTENCY,
    CONFLICT_SOURCE_CHANGED,
    CONFLICT_TARGET_CHANGED,
    EXCLUDED_LOCALE_IS_SOURCE,
    EXCLUDED_LOCALE_NOT_ENABLED,
    LIST_LIMIT,
    Basis,
    Completeness,
    ContentContext,
    FieldError,
    ObjectPage,
    ObjectRef,
    OutcomeState,
    ProtectedRule,
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
from saas_core.content_protocol.units import (
    DATA_PUBLIC,
    DATA_PUBLIC_PERSONAL,
    UNIT_TEXT,
    Target,
    Unit,
    unit_state,
)
from saas_core.content_protocol.writes import (
    GATE_UNKNOWN_UNIT,
    item_digest,
    outcome_from_dict,
    outcome_to_dict,
    write_gate,
)
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.locales import organization_content_locales
from saas_core.modules.core.organizations.models import Organization, OrganizationAuditAction
from saas_core.modules.core.organizations.person_gate import assert_person_required

from .models import (
    CatalogEntry,
    ProfileSubjectKind,
    ProfileTranslationWrite,
    PublicProfile,
    PublicProfileTranslation,
)
from .permissions import PROFILES_MANAGE
from .search_index import catalog_changed

SOURCE_KEY = "profiles.public_profile"
HEADLINE = "headline"
BIO = "bio"
LINK_PREFIX = "link/"
LIMITS = {HEADLINE: 200, BIO: 4000}
LINK_LABEL_LIMIT = 80
#: The source hash of a text written before provenance was kept.
LEGACY_SOURCE = "legacy"
#: A person's decision on a translation (the same label as pages and articles).
REVIEW_GATE = "Decyzja o tłumaczeniu AI"


def link_key(url: str) -> str:
    return LINK_PREFIX + hashlib.sha256(url.encode()).hexdigest()[:12]


@contextmanager
def _tenant(context: ContentContext) -> Iterator[None]:
    """The engine passes the context explicitly; the tables force RLS."""
    if not isinstance(context, TenantContext):
        raise TypeError("A profiles translation call needs a tenant context.")
    with transaction.atomic():
        set_local_organization_id(context.organization_id)
        with activate_tenant_context(context):
            yield


def _profile(context: ContentContext, object_id: UUID, *, lock: bool = False) -> PublicProfile:
    rows = PublicProfile.all_objects.filter(organization_id=context.organization_id, pk=object_id)
    profile = (rows.select_for_update() if lock else rows).first()
    if profile is None:
        raise NotFound("Nie ma takiej wizytówki.")
    return profile


def _row(profile: PublicProfile, locale: str) -> PublicProfileTranslation | None:
    return PublicProfileTranslation.all_objects.filter(
        organization_id=profile.organization_id, profile=profile, locale=locale
    ).first()


def source_units(profile: PublicProfile) -> tuple[Unit, ...]:
    data_class = (
        DATA_PUBLIC
        if profile.subject_kind == ProfileSubjectKind.ORGANIZATION
        else DATA_PUBLIC_PERSONAL
    )
    texts: list[tuple[str, str, int]] = []
    if profile.headline.strip():
        texts.append((HEADLINE, profile.headline, LIMITS[HEADLINE]))
    if profile.bio.strip():
        texts.append((BIO, profile.bio, LIMITS[BIO]))
    for link in profile.links or ():
        texts.append((link_key(link["url"]), link["label"], LINK_LABEL_LIMIT))
    return tuple(
        Unit(
            key=key,
            kind=UNIT_TEXT,
            text=text,
            data_class=data_class,
            max_length=limit,
            placeholder=PLACEHOLDER_PATTERN.search(text) is not None,
        )
        for key, text, limit in texts
    )


def _texts(row: PublicProfileTranslation | None) -> dict[str, str]:
    if row is None:
        return {}
    found = {HEADLINE: row.headline, BIO: row.bio, **(row.link_labels or {})}
    return {key: text for key, text in found.items() if text}


def target_texts(row: PublicProfileTranslation | None, units: Sequence[Unit]) -> dict[str, Target]:
    texts = _texts(row)
    provenance = (row.provenance if row is not None else None) or {}
    targets: dict[str, Target] = {}
    for unit in units:
        text = texts.get(unit.key)
        if not text:
            continue
        stored = provenance.get(unit.key)
        targets[unit.key] = Target(
            text,
            Provenance.from_dict(stored)
            if stored
            else Provenance(origin=ORIGIN_HUMAN, source_hash=LEGACY_SOURCE),
        )
    return targets


def basis_version(profile: PublicProfile) -> str:
    return f"profile:{profile.version}"


def _listed(profile: PublicProfile) -> bool:
    return (
        profile.subject_kind == ProfileSubjectKind.ORGANIZATION
        and CatalogEntry.all_objects.filter(profile_id=profile.id).exists()
    )


def _speaks(organization_id: UUID, locale: str) -> bool:
    """The company's cards already speak this language — their scope is the
    company, so automation may then bring any card into it."""
    return any(
        _texts(row)
        for row in PublicProfileTranslation.all_objects.filter(
            organization_id=organization_id, locale=locale
        )
    )


def _facts(context: ContentContext, profile: PublicProfile, locale: str) -> PublicationFacts:
    return PublicationFacts(
        legal_document=False,
        locale_live=_speaks(profile.organization_id, locale),
        actor_may_publish=context.has_permission(PROFILES_MANAGE),
        target_public=bool(_texts(_row(profile, locale))) and _listed(profile),
    )


def apply_translation(
    profile: PublicProfile,
    locale: str,
    texts: Mapping[str, tuple[str, Provenance]],
    *,
    actor_id: UUID | None,
    flags: Mapping[str, bool] | None = None,
) -> tuple[PublicProfileTranslation, dict[str, Any]]:
    """Writes units of a card's language: the version moves, the history and
    the catalogue follow. Returns the row and what each unit held before."""
    row = _row(profile, locale)
    if row is None:
        row = PublicProfileTranslation(
            organization_id=profile.organization_id, profile=profile, locale=locale, version=0
        )
    before = target_texts(row, source_units(profile)) if row.pk else {}
    replaced: dict[str, Any] = {}
    labels = dict(row.link_labels or {})
    provenance = dict(row.provenance or {})
    for key, (text, origin) in texts.items():
        old = before.get(key)
        replaced[key] = (
            [old.text, old.provenance.as_dict() if old.provenance else {}]
            if old is not None
            else None
        )
        if key == HEADLINE:
            row.headline = text
        elif key == BIO:
            row.bio = text
        elif text:
            labels[key] = text
        else:
            labels.pop(key, None)
        if text:
            provenance[key] = origin.as_dict()
        else:
            provenance.pop(key, None)
    row.link_labels = labels
    row.provenance = provenance
    for flag, value in (flags or {}).items():
        setattr(row, flag, value)
    row.version += 1
    row.full_clean()
    row.save()
    record_audit(
        organization=Organization.objects.get(pk=profile.organization_id),
        action=OrganizationAuditAction.PROFILE_UPDATED,
        actor=User.objects.filter(pk=actor_id).first() if actor_id else None,
        target_type="public_profile_translation",
        target_id=row.id,
        metadata={
            "profile_id": str(profile.id),
            "locale": locale,
            "version": row.version,
            "translated_units": len(texts),
            "origins": sorted({origin.origin for _text, origin in texts.values()}),
        },
    )
    if profile.subject_kind == ProfileSubjectKind.ORGANIZATION:
        catalog_changed(profile.organization_id)
    return row, replaced


class ProfileTranslationSource:
    key = SOURCE_KEY
    module_id = "shared.profiles"
    labels: Mapping[str, str] = {"pl": "Wizytówki", "en": "Business cards"}
    staging: Staging = "live_record"
    bases = frozenset({"published"})
    write_targets = frozenset({"live"})
    translations_publish_separately = False

    def authorize(
        self, *, context: ContentContext, action: SourceAction, object_ids: Sequence[UUID]
    ) -> None:
        with _tenant(context):
            # Reading and translating need only membership: the card is meant for
            # the public, and a translation by someone who may not publish waits.
            if action in ("publish", "withdraw") and not context.has_permission(PROFILES_MANAGE):
                raise PermissionDenied("Brak uprawnienia do wizytówek.")
            found = PublicProfile.all_objects.filter(
                organization_id=context.organization_id, pk__in=list(object_ids)
            ).count()
            if found != len(set(object_ids)):
                raise NotFound("Nie ma takiej wizytówki.")

    def list_objects(
        self,
        *,
        context: ContentContext,
        cursor: str | None,
        limit: int,
        changed_since: datetime | None = None,
    ) -> ObjectPage:
        with _tenant(context):
            rows = PublicProfile.all_objects.filter(organization_id=context.organization_id)
            if changed_since is not None:
                rows = rows.filter(updated_at__gte=changed_since)
            listed = set(
                CatalogEntry.all_objects.filter(
                    organization_id=context.organization_id
                ).values_list("profile_id", flat=True)
            )
            ordered = sorted(
                rows, key=lambda p: (p.subject_kind != ProfileSubjectKind.ORGANIZATION, str(p.id))
            )
            start = int(cursor or 0)
            page = ordered[start : start + min(limit, LIST_LIMIT)]
            end = start + len(page)
            return ObjectPage(
                items=tuple(
                    ObjectRef(
                        object_id=profile.id,
                        label=profile.display_name,
                        scope=str(profile.organization_id),
                        priority=0
                        if profile.subject_kind == ProfileSubjectKind.ORGANIZATION
                        else 1,
                        public=profile.id in listed,
                        published_version=basis_version(profile),
                        working_version=basis_version(profile),
                        changed_at=profile.updated_at,
                    )
                    for profile in page
                ),
                next_cursor=str(end) if end < len(ordered) else None,
            )

    def read(
        self, *, context: ContentContext, object_id: UUID, locale: str, basis: Basis
    ) -> SourceRead:
        if basis not in self.bases:
            raise ValueError(f"Source {self.key} has no {basis!r} basis.")
        with _tenant(context):
            profile = _profile(context, object_id)
            organization = Organization.objects.get(pk=context.organization_id)
            excluded = None
            if locale == profile.locale:
                excluded = EXCLUDED_LOCALE_IS_SOURCE
            elif locale not in organization_content_locales(organization):
                excluded = EXCLUDED_LOCALE_NOT_ENABLED
            units = () if excluded else source_units(profile)
            row = _row(profile, locale)
            return SourceRead(
                object_id=profile.id,
                locale=locale,
                basis="published",
                scope=str(profile.organization_id),
                source_locale=profile.locale,
                basis_version=basis_version(profile),
                target_version=str(row.version if row is not None else 0),
                units=units,
                targets=target_texts(row, units),
                facts=_facts(context, profile, locale),
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
        profile = _profile(context, item.object_id, lock=True)
        keys = tuple(sorted(item.texts))

        def outcome(
            state: OutcomeState, chosen: Sequence[str], reason: str | None, **extra: Any
        ) -> WriteOutcome:
            return WriteOutcome(
                object_id=profile.id,
                locale=item.locale,
                state=state,
                keys=tuple(sorted(chosen)),
                reason=reason,
                **extra,
            )

        digest = item_digest(item)
        seen = ProfileTranslationWrite.all_objects.filter(
            organization_id=profile.organization_id,
            profile=profile,
            locale=item.locale,
            idempotency_key=batch.idempotency_key[:64],
        ).first()
        if seen is not None:
            if seen.request_hash == digest:
                return tuple(outcome_from_dict(stored) for stored in seen.outcomes)
            return (outcome("conflict", keys, CONFLICT_IDEMPOTENCY),)
        row = _row(profile, item.locale)
        if item.basis_version != basis_version(profile):
            return (outcome("conflict", keys, CONFLICT_SOURCE_CHANGED),)
        if item.target_version != str(row.version if row is not None else 0):
            return (outcome("conflict", keys, CONFLICT_TARGET_CHANGED),)
        facts = replace(
            _facts(context, profile, item.locale),
            object_published_in_job=profile.id in published_now,
            published_in_job=len(published_now - {profile.id}),
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
                profile, batch, item, digest, (outcome("refused", keys, decision.reason),), {}
            )
        units = {unit.key: unit for unit in source_units(profile)}
        current = target_texts(row, list(units.values()))
        terms = self.protected_terms(context=context, object_id=profile.id)
        written: dict[str, tuple[str, Provenance]] = {}
        proposals: list[str] = []
        errors: list[FieldError] = []
        for key, (text, provenance) in item.texts.items():
            unit = units.get(key)
            if unit is None:
                errors.append(FieldError(f"units.{key}", GATE_UNKNOWN_UNIT, "No such unit."))
                continue
            error = write_gate(unit, text, terms)
            if error is not None:
                errors.append(error)
                continue
            if batch.protected != "overwrite" and unit_state(unit, current.get(key)).protected:
                proposals.append(key)
            else:
                written[key] = (text, provenance)
        results: list[WriteOutcome] = []
        replaced: dict[str, Any] = {}
        if written:
            state: OutcomeState = decision.outcome
            if state == "live":
                row, replaced = apply_translation(
                    profile, item.locale, written, actor_id=context.actor_id
                )
                published_now.add(profile.id)
            results.append(
                outcome(
                    state,
                    list(written),
                    decision.reason,
                    target_version=str(row.version if row is not None else 0),
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
        return self._receipt(profile, batch, item, digest, tuple(results), replaced)

    @staticmethod
    def _receipt(
        profile: PublicProfile,
        batch: WriteBatch,
        item: WriteItem,
        digest: str,
        outcomes: tuple[WriteOutcome, ...],
        replaced: dict[str, Any],
    ) -> tuple[WriteOutcome, ...]:
        ProfileTranslationWrite.all_objects.create(
            organization_id=profile.organization_id,
            profile=profile,
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
            profile = _profile(context, object_id)
            units = source_units(profile)
            targets = target_texts(_row(profile, locale), units)
            untranslated = tuple(
                unit.key
                for unit in units
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
        """The card's own name: a company's kept as written, a person's
        transliterated into Cyrillic like any name."""
        profile = PublicProfile.all_objects.filter(
            organization_id=context.organization_id, pk=object_id
        ).first()
        if profile is None or not profile.display_name.strip():
            return ()
        rule: ProtectedRule = (
            "keep" if profile.subject_kind == ProfileSubjectKind.ORGANIZATION else "name"
        )
        return (ProtectedTerm(text=profile.display_name.strip(), rule=rule),)

    def review(
        self,
        *,
        context: ContentContext,
        action: ReviewAction,
        items: Sequence[ReviewItem],
        idempotency_key: str,
    ) -> tuple[WriteOutcome, ...]:
        """A person's decision. Accepting a live record is the engine's write;
        withdrawing takes the card's language down."""
        with _tenant(context):
            assert_person_required(context, REVIEW_GATE)  # type: ignore[arg-type]
        self.authorize(context=context, action="publish", object_ids=[i.object_id for i in items])
        outcomes: list[WriteOutcome] = []
        if action != "withdraw":
            return ()
        with _tenant(context):
            for item in items:
                profile = _profile(context, item.object_id, lock=True)
                row = _row(profile, item.locale)
                if row is None:
                    continue
                apply_translation(
                    profile,
                    item.locale,
                    {key: ("", Provenance(ORIGIN_HUMAN, LEGACY_SOURCE)) for key in _texts(row)},
                    actor_id=context.actor_id,
                )
                outcomes.append(
                    WriteOutcome(profile.id, item.locale, "draft", keys=(), reason="withdrawn")
                )
        return tuple(outcomes)

    def revert(
        self, *, context: ContentContext, job_ref: str, idempotency_key: str
    ) -> tuple[WriteOutcome, ...]:
        """Puts back what each of the job's writes replaced, newest first."""
        touched: list[tuple[UUID, str]] = []
        with _tenant(context):
            receipts = ProfileTranslationWrite.all_objects.filter(
                organization_id=context.organization_id, job_ref=job_ref
            ).order_by("-created_at")
            for receipt in receipts:
                if not receipt.replaced:
                    continue
                profile = _profile(context, receipt.profile_id, lock=True)
                previous: dict[str, tuple[str, Provenance]] = {}
                for key, value in receipt.replaced.items():
                    if value is None:
                        previous[key] = ("", Provenance(ORIGIN_HUMAN, LEGACY_SOURCE))
                    else:
                        previous[key] = (str(value[0]), Provenance.from_dict(dict(value[1])))
                apply_translation(profile, receipt.locale, previous, actor_id=context.actor_id)
                receipt.replaced = {}
                receipt.save(update_fields=["replaced"])
                if (profile.id, receipt.locale) not in touched:
                    touched.append((profile.id, receipt.locale))
        return tuple(
            WriteOutcome(object_id, locale, "live", keys=(), reason=None)
            for object_id, locale in touched
        )


PROFILE_SOURCE = ProfileTranslationSource()


def register_profile_source() -> None:
    registry.register_translation_source(PROFILE_SOURCE)


def notify_card_changed(*, context: Any, profile_id: UUID, change: str = "changed") -> None:
    """A card's public text changed, in the transaction that changed it (§8.1)."""
    registry.notify_source_changed(
        context=context,
        source_key=SOURCE_KEY,
        object_ids=[profile_id],
        change=change,  # type: ignore[arg-type]
        cause="api_key" if getattr(context, "principal_kind", "") == "api_key" else "user",
    )
