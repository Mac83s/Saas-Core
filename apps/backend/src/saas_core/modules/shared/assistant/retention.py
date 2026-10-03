"""The assistant's retention, under the common privacy run (ADR-078; settings
plan D1–D2; ADR-076, „profil firmy i konfigurator” pkt 7).

Two sweeps, both on the platform's setting
`assistant.retention.conversation_days` (`platform_days`):

- conversations leave with their transcript so many days after their last
  message;
- a saved state of the company's profile leaves so many days after it stopped
  being the current one. The newest state is the profile and is never due.

The run visits every company in its own tenant and transaction, takes at most
its limit per company and writes one history row with the count — never a
person, a word of a conversation or a value of the profile. Nothing here is a
company's own choice, so there is no grace period: the setting's minimum of
one day is the guard.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.db.models import Max, QuerySet

from saas_core.modules.core.organizations.api import (
    RetentionSweep,
    platform_days,
    register_retention_sweep,
)

from .models import AssistantConversation, AssistantProfileVersion
from .settings_spec import RETENTION_DAYS

CONVERSATIONS = "assistant.conversations"
PROFILE_VERSIONS = "assistant.profile_versions"


def conversations_due(organization_id: UUID, cutoff: datetime) -> QuerySet[AssistantConversation]:
    """Conversations nobody wrote in since before `cutoff`."""
    return AssistantConversation.all_objects.filter(
        organization_id=organization_id, updated_at__lt=cutoff
    )


def erase_conversations(organization_id: UUID, cutoff: datetime, limit: int) -> int:
    """Removes up to `limit` due conversations with their turns and messages.
    A conversation somebody writes in right now is locked by that write and
    skipped; the delete asks the date again, so one that got a message between
    the pick and the delete stays."""
    picked = list(
        conversations_due(organization_id, cutoff)
        .select_for_update(skip_locked=True)
        .order_by("updated_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    _, removed = conversations_due(organization_id, cutoff).filter(pk__in=picked).delete()
    return int(removed.get(AssistantConversation._meta.label, 0))


def profile_versions_due(
    organization_id: UUID, cutoff: datetime
) -> QuerySet[AssistantProfileVersion]:
    """Saved states of the profile that a later state replaced before
    `cutoff`. Versions are saved one after another, so a state was replaced
    when the next one was saved: every state below the newest one saved before
    `cutoff` is due, and the current state never is."""
    versions = AssistantProfileVersion.all_objects.filter(organization_id=organization_id)
    replaced_by = versions.filter(created_at__lt=cutoff).aggregate(newest=Max("version"))["newest"]
    if replaced_by is None:
        return versions.none()
    return versions.filter(version__lt=replaced_by)


def erase_profile_versions(organization_id: UUID, cutoff: datetime, limit: int) -> int:
    picked = list(
        profile_versions_due(organization_id, cutoff)
        .select_for_update(skip_locked=True)
        .order_by("version")
        .values_list("id", flat=True)[:limit]
    )
    _, removed = profile_versions_due(organization_id, cutoff).filter(pk__in=picked).delete()
    return int(removed.get(AssistantProfileVersion._meta.label, 0))


def _conversations_count(organization_id: UUID, cutoff: datetime) -> int:
    return conversations_due(organization_id, cutoff).count()


def _profile_versions_count(organization_id: UUID, cutoff: datetime) -> int:
    return profile_versions_due(organization_id, cutoff).count()


_RULE = platform_days(RETENTION_DAYS.key)
#: Made once, so registering again registers the same thing.
SWEEPS = (
    RetentionSweep(
        key=CONVERSATIONS, rule=_RULE, due=_conversations_count, erase=erase_conversations
    ),
    RetentionSweep(
        key=PROFILE_VERSIONS,
        rule=_RULE,
        due=_profile_versions_count,
        erase=erase_profile_versions,
    ),
)


def register_retention() -> None:
    """From `AssistantConfig.ready`: both sweeps on the platform's days."""
    for sweep in SWEEPS:
        register_retention_sweep(sweep)
