"""The texts of a whole site as a translation source: `sites.site_texts`
(ADR-069, ADR-070 pkt 15; plan TL11c).

One object per site: its tagline, footer, footer link labels, collection and
tag names (`site_texts`). Only the published state is a basis; a write is
accepted (`live`) or waits for a person (`pending`) in `SiteTextTranslation`,
and `publish` is a derived publication of what is public with the texts the
job wrote. Undoing a job puts back each text it replaced.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from saas_core.content_protocol import registry
from saas_core.content_protocol.policy import (
    REASON_OVERWRITES_HUMAN,
    PublicationFacts,
    decide_publication,
)
from saas_core.content_protocol.sources import (
    CONFLICT_IDEMPOTENCY,
    CONFLICT_SOURCE_CHANGED,
    CONFLICT_TARGET_CHANGED,
    EXCLUDED_LOCALE_IS_SOURCE,
    EXCLUDED_LOCALE_NOT_ENABLED,
    EXCLUDED_SOURCE_UNPUBLISHED,
    LIST_LIMIT,
    Basis,
    Completeness,
    ContentContext,
    FieldError,
    ObjectPage,
    ObjectRef,
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
from saas_core.content_protocol.units import unit_state
from saas_core.modules.core.organizations.person_gate import assert_person_required
from saas_core.modules.shared.billing.api import authorize_entitled

from .language_decisions import REVIEW_GATE
from .language_versions import site_locales
from .models import (
    PublicationReason,
    Site,
    SiteTextTranslation,
    SiteTextWrite,
)
from .permissions import SITE_CONTENT_EDIT, SITE_PUBLISH, SITES_ENABLED
from .services import SiteNotFound
from .site_texts import (
    basis_token,
    published_appearance,
    republish_site_texts,
    site_text_units,
    store_row,
    target_token,
    targets,
    translation_rows,
)
from .source_changes import SITE_TEXTS_SOURCE_KEY
from .translation_source import (
    GATE_UNKNOWN_UNIT,
    _gate,
    _item_digest,
    _outcome_dict,
    _outcome_from,
    _tenant,
    _tenant_context,
)

SOURCE_KEY = SITE_TEXTS_SOURCE_KEY


class SiteTextSource:
    key = SOURCE_KEY
    module_id = "shared.sites"
    labels: Mapping[str, str] = {
        "pl": "Teksty stron firm (hasło, stopka, nazwy)",
        "en": "Company site texts (tagline, footer, names)",
    }
    staging: Staging = "versioned"
    bases: frozenset[str] = frozenset({"published"})
    write_targets: frozenset[str] = frozenset({"pending", "live"})
    translations_publish_separately = False

    def authorize(
        self, *, context: ContentContext, action: SourceAction, object_ids: Sequence[UUID]
    ) -> None:
        with _tenant(context):
            _authorize(context, action, object_ids)

    def list_objects(
        self,
        *,
        context: ContentContext,
        cursor: str | None,
        limit: int,
        changed_since: datetime | None = None,
    ) -> ObjectPage:
        with _tenant(context):
            _authorize(context, "read", ())
            sites = Site.all_objects.select_related("current_publication").filter(
                organization_id=context.organization_id
            )
            if changed_since is not None:
                sites = sites.filter(updated_at__gte=changed_since)
            ordered = list(sites.order_by("id"))
            start = int(cursor or 0)
            chunk = ordered[start : start + min(limit, LIST_LIMIT)]
            end = start + len(chunk)
            items = []
            for site in chunk:
                units = site_text_units(site, published_appearance(site))
                public = site.current_publication is not None and bool(units)
                items.append(
                    ObjectRef(
                        object_id=site.id,
                        label=site.name,
                        scope=str(site.id),
                        priority=2,
                        public=public,
                        published_version=basis_token(units) if public else None,
                        working_version=None,
                        changed_at=site.updated_at,
                    )
                )
            return ObjectPage(
                items=tuple(items), next_cursor=str(end) if end < len(ordered) else None
            )

    def read(
        self, *, context: ContentContext, object_id: UUID, locale: str, basis: Basis
    ) -> SourceRead:
        with _tenant(context):
            _authorize(context, "read", (object_id,))
            return _read(context, _site(context, object_id), locale)

    def write(self, *, context: ContentContext, batch: WriteBatch) -> tuple[WriteOutcome, ...]:
        if batch.source_key != self.key:
            raise ValueError("The batch is for another source.")
        with _tenant(context):
            _authorize(context, "translate", [item.object_id for item in batch.items])
            published_now = set(batch.published_in_job)
            outcomes: list[WriteOutcome] = []
            for item in batch.items:
                outcomes.extend(_write_item(context, batch, item, published_now))
            return tuple(outcomes)

    def publish(
        self, *, context: ContentContext, scope: str, job_ref: str, idempotency_key: str
    ) -> str | None:
        """One derived publication of the site with the texts this job made
        current, per language; nothing else of the site goes with it."""
        with _tenant(context):
            _authorize(context, "publish", ())
            site = _site(context, UUID(scope), lock=True)
            touched: dict[str, set[str]] = {}
            for row in SiteTextTranslation.all_objects.filter(
                organization_id=site.organization_id, site_id=site.id, origin_ref=job_ref
            ):
                touched.setdefault(row.locale, set()).add(row.anchor)
            publication = None
            for locale, keys in sorted(touched.items()):
                publication = (
                    republish_site_texts(
                        context,
                        _site(context, site.id),
                        locale,
                        reason=PublicationReason.TRANSLATION_JOB,
                        idempotency_key=f"{idempotency_key}:{locale}",
                        keys=keys,
                    )
                    or publication
                )
            return str(publication.id) if publication is not None else None

    def completeness(
        self, *, context: ContentContext, object_id: UUID, locale: str
    ) -> Completeness:
        with _tenant(context):
            _authorize(context, "read", (object_id,))
            read = _read(context, _site(context, object_id), locale)
            if read.excluded:
                return Completeness(complete=False, publishable=False, reasons=(read.excluded,))
            untranslated = tuple(
                unit.key
                for unit in read.units
                if unit_state(unit, read.targets.get(unit.key)).status in ("missing", "blocked")
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
        """The site's name and the company's — brands are kept as written."""
        with _tenant(context):
            site = _site(context, object_id)
            names = {site.name.strip(), site.organization.name.strip()}
            return tuple(ProtectedTerm(text=name, rule="keep") for name in sorted(names) if name)

    def review(
        self,
        *,
        context: ContentContext,
        action: ReviewAction,
        items: Sequence[ReviewItem],
        idempotency_key: str,
    ) -> tuple[WriteOutcome, ...]:
        """A person's decision on waiting texts of one language of a site:
        accepting makes them current and publishes them."""
        if action not in ("accept", "discard"):
            raise ValueError(f"Review action {action!r} is not offered for site texts.")
        with _tenant(context):
            authorize_entitled(
                SITE_PUBLISH if action == "accept" else SITE_CONTENT_EDIT, SITES_ENABLED
            )
            assert_person_required(_tenant_context(context), REVIEW_GATE)
            return tuple(
                _decide(context, action, item, f"{idempotency_key}:{item.object_id}:{item.locale}")
                for item in items
            )

    def revert(
        self, *, context: ContentContext, job_ref: str, idempotency_key: str
    ) -> tuple[WriteOutcome, ...]:
        """Each text the job wrote goes back to what it replaced; waiting ones
        it left are dropped. The operator's command reverts in the job's own
        context, so no person gate here."""
        with _tenant(context):
            _authorize(context, "publish", ())
            rows = SiteTextTranslation.all_objects.select_for_update().filter(
                organization_id=context.organization_id
            )
            touched: dict[tuple[UUID, str], set[str]] = {}
            for row in rows.filter(origin_ref=job_ref):
                row.text, row.provenance = row.previous_text, row.previous_provenance
                row.previous_text, row.previous_provenance, row.origin_ref = "", None, ""
                row.save()
                touched.setdefault((row.site_id, row.locale), set()).add(row.anchor)
            for row in rows.filter(pending_ref=job_ref):
                row.pending_text, row.pending_provenance = "", None
                row.pending_reason, row.pending_ref = "", ""
                row.save()
                touched.setdefault((row.site_id, row.locale), set())
            outcomes: list[WriteOutcome] = []
            for (site_id, locale), keys in sorted(touched.items()):
                site = _site(context, site_id, lock=True)
                if keys:
                    republish_site_texts(
                        context,
                        site,
                        locale,
                        reason=PublicationReason.TRANSLATION_REVERT,
                        idempotency_key=f"{idempotency_key}:{site_id}:{locale}",
                        keys=keys,
                    )
                outcomes.append(
                    WriteOutcome(
                        object_id=site_id,
                        locale=locale,
                        state="live",
                        keys=(),
                        reason="reverted",
                        target_version=target_token(translation_rows(site, locale)),
                    )
                )
            return tuple(outcomes)


SITE_TEXT_SOURCE = SiteTextSource()


# -- reading -------------------------------------------------------------------


def _authorize(context: ContentContext, action: SourceAction, object_ids: Sequence[UUID]) -> None:
    authorize_entitled(
        SITE_PUBLISH if action in ("publish", "withdraw") else SITE_CONTENT_EDIT, SITES_ENABLED
    )
    wanted = set(object_ids)
    if wanted and Site.all_objects.filter(
        organization_id=context.organization_id, id__in=wanted
    ).count() != len(wanted):
        raise SiteNotFound


def _site(context: ContentContext, object_id: UUID, *, lock: bool = False) -> Site:
    sites = Site.all_objects.select_related("current_publication", "organization")
    if lock:
        sites = sites.select_for_update(of=("self",))
    site = sites.filter(pk=object_id, organization_id=context.organization_id).first()
    if site is None:
        raise SiteNotFound
    return site


def _read(context: ContentContext, site: Site, locale: str) -> SourceRead:
    excluded = None
    if locale == site.default_locale:
        excluded = EXCLUDED_LOCALE_IS_SOURCE
    elif locale not in site_locales(site):
        excluded = EXCLUDED_LOCALE_NOT_ENABLED
    elif site.current_publication is None:
        excluded = EXCLUDED_SOURCE_UNPUBLISHED
    units = () if excluded else site_text_units(site, published_appearance(site))
    rows = translation_rows(site, locale)
    return SourceRead(
        object_id=site.id,
        locale=locale,
        basis="published",
        scope=str(site.id),
        source_locale=site.default_locale,
        basis_version=basis_token(units) if not excluded else "",
        target_version=target_token(rows),
        units=units,
        targets=targets(units, rows),
        facts=PublicationFacts(
            legal_document=False,
            locale_live=_locale_live(site, locale),
            actor_may_publish=context.has_permission(SITE_PUBLISH),
        ),
        excluded=excluded,
    )


def _locale_live(site: Site, locale: str) -> bool:
    """The company shows the language already: on this site's pages, or in
    site texts published anywhere — the footer alone opens no language."""
    publication = site.current_publication
    if publication is not None and locale in (publication.snapshot.get("live_locales") or []):
        return True
    return (
        SiteTextTranslation.all_objects.filter(
            organization_id=site.organization_id, locale=locale
        )
        .exclude(text="")
        .exists()
    )


# -- writing -------------------------------------------------------------------


def _write_item(
    context: ContentContext,
    batch: WriteBatch,
    item: WriteItem,
    published_now: set[UUID],
) -> tuple[WriteOutcome, ...]:
    keys = tuple(sorted(item.texts))

    def outcome(
        state: str, chosen: Sequence[str], reason: str | None, **extra: Any
    ) -> WriteOutcome:
        return WriteOutcome(
            object_id=item.object_id,
            locale=item.locale,
            state=state,  # type: ignore[arg-type]
            keys=tuple(sorted(chosen)),
            reason=reason,
            **extra,
        )

    site = _site(context, item.object_id, lock=True)
    receipt_key = hashlib.sha256(batch.idempotency_key.encode()).hexdigest()
    digest = _item_digest(item)
    done = SiteTextWrite.all_objects.filter(
        organization_id=site.organization_id,
        site_id=site.id,
        locale=item.locale,
        idempotency_key=receipt_key,
    ).first()
    if done is not None:
        if done.request_hash != digest:
            return (outcome("conflict", keys, CONFLICT_IDEMPOTENCY),)
        return tuple(_outcome_from(stored) for stored in done.outcomes)

    def finish(results: Sequence[WriteOutcome]) -> tuple[WriteOutcome, ...]:
        try:
            with transaction.atomic():
                SiteTextWrite.all_objects.create(
                    organization_id=site.organization_id,
                    site=site,
                    locale=item.locale,
                    idempotency_key=receipt_key,
                    request_hash=digest,
                    job_ref=batch.trigger.job_ref or "",
                    outcomes=[_outcome_dict(result) for result in results],
                )
        except IntegrityError:
            pass
        return tuple(results)

    read = _read(context, site, item.locale)
    if read.excluded:
        return finish((outcome("refused", keys, read.excluded),))
    if item.basis_version != read.basis_version:
        return finish((outcome("conflict", keys, CONFLICT_SOURCE_CHANGED),))
    if item.target_version != read.target_version:
        return finish((outcome("conflict", keys, CONFLICT_TARGET_CHANGED),))
    facts = replace(
        read.facts,
        object_published_in_job=site.id in published_now,
        published_in_job=len(published_now - {site.id}),
    )
    decision = decide_publication(
        policy=registry.translation_policy(organization_id=context.organization_id),
        requested=item.requested,
        requested_reason=item.reason,
        trigger=batch.trigger,
        facts=facts,
    )
    if decision.outcome == "refused":
        return finish((outcome("refused", keys, decision.reason),))
    units = {unit.key: unit for unit in read.units}
    terms = SITE_TEXT_SOURCE.protected_terms(context=context, object_id=site.id)
    written: dict[str, tuple[str, dict[str, Any]]] = {}
    proposals: dict[str, tuple[str, dict[str, Any]]] = {}
    errors: list[FieldError] = []
    for key, (text, provenance) in item.texts.items():
        unit = units.get(key)
        if unit is None:
            errors.append(FieldError(f"units.{key}", GATE_UNKNOWN_UNIT, "No such unit."))
            continue
        error = _gate(unit, text, terms)
        if error is not None:
            errors.append(error)
            continue
        if batch.protected != "overwrite" and unit_state(unit, read.targets.get(key)).protected:
            proposals[key] = (text, provenance.as_dict())
        else:
            written[key] = (text, provenance.as_dict())
    job_ref = batch.trigger.job_ref or ""
    state = decision.outcome
    current = written if state == "live" else {}
    held = {**(written if state != "live" else {}), **proposals}
    for key, (text, stored) in current.items():
        row = store_row(site, item.locale, units[key])
        if row.origin_ref != job_ref or not job_ref:
            row.previous_text, row.previous_provenance = row.text, row.provenance
        row.text, row.provenance, row.origin_ref = text, stored, job_ref
        row.save()
    for key, (text, stored) in held.items():
        row = store_row(site, item.locale, units[key])
        row.pending_text, row.pending_provenance = text, stored
        row.pending_reason = (
            REASON_OVERWRITES_HUMAN if key in proposals else (decision.reason or "")
        )[:40]
        row.pending_ref = job_ref
        row.save()
    version = target_token(translation_rows(site, item.locale))
    results: list[WriteOutcome] = []
    if current:
        published_now.add(site.id)
        results.append(outcome("live", list(current), decision.reason, target_version=version))
    waiting = [key for key in held if key not in proposals]
    if waiting:
        results.append(outcome("pending", waiting, decision.reason, target_version=version))
    if proposals:
        results.append(
            outcome("pending", list(proposals), REASON_OVERWRITES_HUMAN, target_version=version)
        )
    if errors:
        results.append(
            outcome(
                "pending",
                [error.field.removeprefix("units.") for error in errors],
                "gate_failed",
                errors=tuple(errors),
            )
        )
    return finish(results)


# -- a person's decisions ------------------------------------------------------


def _decide(
    context: ContentContext, action: ReviewAction, item: ReviewItem, key: str
) -> WriteOutcome:
    site = _site(context, item.object_id, lock=True)
    rows = translation_rows(site, item.locale, lock=True)
    if item.expected_version is not None and item.expected_version != target_token(rows):
        return WriteOutcome(
            object_id=site.id,
            locale=item.locale,
            state="conflict",
            keys=(),
            reason=CONFLICT_TARGET_CHANGED,
        )
    waiting = [row for row in rows if row.pending_text]
    if not waiting:
        return WriteOutcome(
            object_id=site.id,
            locale=item.locale,
            state="conflict",
            keys=(),
            reason=CONFLICT_TARGET_CHANGED,
        )
    for row in waiting:
        if action == "accept":
            # The person's decision from now on: undoing the job leaves it.
            row.previous_text, row.previous_provenance = row.text, row.provenance
            row.text, row.provenance = row.pending_text, row.pending_provenance
            row.origin_ref = ""
        row.pending_text, row.pending_provenance = "", None
        row.pending_reason, row.pending_ref = "", ""
        row.save()
    if action == "accept":
        republish_site_texts(
            context,
            site,
            item.locale,
            reason=PublicationReason.LOCALE_ACCEPT,
            idempotency_key=key,
            keys={row.anchor for row in waiting},
        )
    return WriteOutcome(
        object_id=site.id,
        locale=item.locale,
        state="live" if action == "accept" else "refused",
        keys=tuple(sorted(row.anchor for row in waiting)),
        reason=None if action == "accept" else "discarded",
        target_version=target_token(translation_rows(site, item.locale)),
    )


def register_site_text_source() -> None:
    registry.register_translation_source(SITE_TEXT_SOURCE)


__all__ = ["SITE_TEXT_SOURCE", "SOURCE_KEY", "register_site_text_source"]
