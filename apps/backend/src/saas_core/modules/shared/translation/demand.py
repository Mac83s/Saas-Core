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

from saas_core.content_protocol.registry import SourceChangeNotice, translation_source
from saas_core.modules.core.organizations.command_registry import organization_modules
from saas_core.modules.core.organizations.context import set_local_organization_id

from .models import TranslationDemand, TranslationSettings
from .services import settings_state
from .settings_spec import AUTO_CHANGES

logger = logging.getLogger(__name__)

MODULE_ID = "shared.translation"
#: How long a change waits for the next one before its job starts.
DEMAND_WAIT = timedelta(minutes=5)
#: However often the object changes, its job starts this long after the first.
DEMAND_MAX_WAIT = timedelta(minutes=30)


def on_source_change(notice: SourceChangeNotice) -> None:
    """The registry's listener: the write waits for the commit (§8.2.3)."""
    transaction.on_commit(lambda: record_demand(notice), robust=True)


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


def record_demand(notice: SourceChangeNotice) -> None:
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
