"""Demand for automatic translation (TL21a, translation-sources.md §8.2–8.3).

A module reports that an object's public source text changed, in the
transaction that changed it. The engine's listener only schedules the write
after commit, so a rolled-back save leaves no demand and a failure here never
fails the company's work. The row is the coalescing: repeated changes of one
object move its `due_at` to five minutes after the latest, never later than
thirty after the first. Nothing is recorded unless the automation is on with
a person's consent and the company's type composes both this module and the
source's (ADR-050).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.content_protocol.registry import (
    SourceChangeNotice,
    translation_source,
    translation_sources,
)
from saas_core.content_protocol.sources import ContentContext, TranslationSource
from saas_core.modules.core.organizations.command_registry import organization_modules
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    current_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import Organization

from .models import ReviewState, TranslationDemand, TranslationReviewItem, TranslationSettings
from .services import settings_state
from .settings_spec import AUTO_CHANGES

logger = logging.getLogger(__name__)

MODULE_ID = "shared.translation"
#: A review item: the original was withdrawn, its translation is still public.
SOURCE_WITHDRAWN = "source_withdrawn"
#: How long a change waits for the next one before its job starts.
DEMAND_WAIT = timedelta(minutes=5)
#: However often the object changes, its job starts this long after the first.
DEMAND_MAX_WAIT = timedelta(minutes=30)


def on_source_change(notice: SourceChangeNotice) -> None:
    """The registry's listener: the write waits for the commit (§8.2.3). The
    context of whoever changed the source goes along: a withdrawal reads the
    translations still public as that person."""
    context = current_tenant_context()
    transaction.on_commit(lambda: record_demand(notice, context), robust=True)


def _cause(notice: SourceChangeNotice) -> str:
    return f"{notice.cause}:{notice.actor_id}" if notice.actor_id else notice.cause


def automation_on(organization_id: UUID, source_key: str) -> bool:
    """The company may get automatic jobs from this source now."""
    try:
        source = translation_source(source_key)
    except LookupError:
        return False
    modules = organization_modules(organization_id)
    if MODULE_ID not in modules or source.module_id not in modules:
        return False
    row = TranslationSettings.all_objects.filter(organization_id=organization_id).first()
    if row is None or row.auto_consent_membership_id is None:
        return False
    # On, and a monthly limit above 0 after the operator's cap.
    return bool(settings_state(organization_id)["values"][AUTO_CHANGES.key]["effective"])


def record_demand(notice: SourceChangeNotice, context: TenantContext | None = None) -> None:
    with transaction.atomic():
        set_local_organization_id(notice.organization_id)
        rows = TranslationDemand.all_objects.filter(
            organization_id=notice.organization_id,
            source_key=notice.source_key,
            object_id__in=notice.object_ids,
        )
        if notice.change != "changed":
            # A withdrawn or deleted object has nothing left to translate.
            rows.delete()
            if notice.change == "withdrawn" and context is not None:
                _open_withdrawals(notice, context)
            return
        if not automation_on(notice.organization_id, notice.source_key):
            return
        now = timezone.now()
        for object_id in notice.object_ids:
            _touch(notice, object_id, now)


def _touch(notice: SourceChangeNotice, object_id: UUID, now: datetime) -> None:
    lookup = {
        "organization_id": notice.organization_id,
        "source_key": notice.source_key,
        "object_id": object_id,
    }
    row = TranslationDemand.all_objects.select_for_update().filter(**lookup).first()
    if row is None:
        try:
            with transaction.atomic():
                TranslationDemand.all_objects.create(
                    **lookup,
                    cause=_cause(notice)[:80],
                    first_at=now,
                    due_at=now + DEMAND_WAIT,
                )
            return
        except IntegrityError:
            # Another change of the same object got there first.
            row = TranslationDemand.all_objects.select_for_update().get(**lookup)
    row.due_at = min(now + DEMAND_WAIT, row.first_at + DEMAND_MAX_WAIT)
    row.save(update_fields=["due_at", "updated_at"])


#: How far back the daily repair looks: a day and an hour, so a tick that ran
#: late still overlaps the one before.
RECONCILE_WINDOW = timedelta(hours=25)


def reconcile_demand(now: datetime | None = None) -> int:
    """Once a day: a change whose notice was lost — the process died between
    the commit and the callback — gets its demand the same way (§8.4). Objects
    whose translations are fresh cost a quote and are dropped by the run."""
    from saas_core.modules.shared.billing.api import billing_organization_ids  # noqa: PLC0415

    from .worker import person_context  # noqa: PLC0415 — the worker imports the jobs

    now = now or timezone.now()
    recorded = 0
    for organization_id in billing_organization_ids():
        with transaction.atomic():
            set_local_organization_id(organization_id)
            row = TranslationSettings.all_objects.filter(organization_id=organization_id).first()
            if row is None or row.auto_consent_membership_id is None:
                continue
            context = person_context(organization_id, row.auto_consent_membership_id)
            if context is None:
                continue
            for source in translation_sources():
                if not automation_on(organization_id, source.key):
                    continue
                try:
                    with transaction.atomic():
                        recorded += _repair(organization_id, source, context, now)
                except Exception as error:
                    # One source refusing (a plan, a right) never stops the others.
                    logger.warning(
                        "translation_demand_reconcile_skipped",
                        extra={
                            "organization_id": str(organization_id),
                            "source_key": source.key,
                            "error": type(error).__name__,
                        },
                    )
    return recorded


def _repair(
    organization_id: UUID, source: TranslationSource, context: ContentContext, now: datetime
) -> int:
    changed = _changed_public(source, context, now - RECONCILE_WINDOW)
    if changed:
        record_demand(
            SourceChangeNotice(
                organization_id=organization_id,
                source_key=source.key,
                object_ids=tuple(changed),
                change="changed",
                cause="schedule",
                actor_id=None,
                at=now,
            )
        )
    return len(changed)


def _changed_public(
    source: TranslationSource, context: ContentContext, since: datetime
) -> list[UUID]:
    found: list[UUID] = []
    cursor: str | None = None
    while True:
        page = source.list_objects(context=context, cursor=cursor, limit=200, changed_since=since)
        found.extend(ref.object_id for ref in page.items if ref.public)
        cursor = page.next_cursor
        if cursor is None:
            return found


def _open_withdrawals(notice: SourceChangeNotice, context: TenantContext) -> None:
    """The original is down, its translations published on their own are not:
    one review item per language still public asks a person whether to take it
    down too (§8.3 pkt 3). Whatever else waited for that pair is moot."""
    try:
        source = translation_source(notice.source_key)
    except LookupError:
        return
    if not source.translations_publish_separately:
        return
    organization = Organization.objects.get(pk=notice.organization_id)
    with activate_tenant_context(context):
        for object_id in notice.object_ids:
            for locale in organization.public_locales or ():
                try:
                    read = source.read(
                        context=context, object_id=object_id, locale=locale, basis="published"
                    )
                except (APIException, LookupError):
                    continue
                if not read.facts.target_public:
                    continue
                pair = {
                    "organization_id": notice.organization_id,
                    "source_key": notice.source_key,
                    "object_id": object_id,
                    "locale": locale,
                }
                TranslationReviewItem.all_objects.filter(**pair, state=ReviewState.OPEN).update(
                    state=ReviewState.SUPERSEDED, texts={}, updated_at=timezone.now()
                )
                TranslationReviewItem.all_objects.create(
                    **pair,
                    basis="published",
                    basis_version=read.basis_version,
                    target_version=read.target_version or "",
                    reason=SOURCE_WITHDRAWN,
                )
