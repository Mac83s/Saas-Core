"""Stan tłumaczeń jednej firmy dla wsparcia, do czasu widoku operatora w panelu
(plan TL11d; „Widok jednej firmy”: ustawienia, zgoda, zużycie, zadania, stan).

Tylko odczyt, ale w cudzym tenancie: wymaga konta is_staff z MFA i powodu, a
każde otwarcie zostaje w historii firmy. Teksty firmy (tytuły, treści) nie są
wypisywane — tylko klucze źródeł, identyfikatory obiektów, języki i stany.

    python manage.py translation_support_overview --organization <uuid> \\
        --operator <e-mail> --reason "…"
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from saas_core.content_protocol import registry
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.locales import organization_content_locales
from saas_core.modules.core.organizations.models import Organization

from ...automation import automatic_credits_this_month
from ...engine_policy import effective_mode, operator_override
from ...models import (
    DemandState,
    ReviewState,
    TranslationDemand,
    TranslationJob,
    TranslationJobItem,
    TranslationReviewItem,
    TranslationSettings,
)
from ...settings_spec import mass_publication_cap
from ..operator import operator_user, reason_of

logger = logging.getLogger("saas_core.security")

SUPPORT_OVERVIEW_VIEWED = "translation.support_overview_viewed"
#: How far back the job and item counts reach.
RECENT_DAYS = 30


class Command(BaseCommand):
    help = "Wypisuje stan tłumaczeń jednej firmy dla wsparcia (odczyt z wpisem w historii)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--organization", required=True, help="Identyfikator organizacji.")
        parser.add_argument("--operator", required=True, help="Adres operatora; is_staff i MFA.")
        parser.add_argument("--reason", help="Dlaczego. Trafia do historii firmy.")

    @transaction.atomic
    def handle(self, *_args: Any, **options: Any) -> None:
        try:
            organization_id = UUID(str(options["organization"]))
        except ValueError:
            raise CommandError("Nieprawidłowy identyfikator organizacji.") from None
        operator = operator_user(options["operator"])
        reason = reason_of(options["reason"])
        # Every table read here forces row-level security: the command works
        # inside the organization the operator names.
        set_local_organization_id(organization_id)
        organization = Organization.objects.filter(pk=organization_id).first()
        if organization is None:
            raise CommandError("Organizacja nie istnieje.")
        now = timezone.now()
        for line in overview(organization, now):
            self.stdout.write(line)
        record_audit(
            organization=organization,
            action=SUPPORT_OVERVIEW_VIEWED,
            actor=operator,
            target_type="organization",
            target_id=organization.id,
            metadata={"reason": reason},
        )
        logger.warning(
            "translation_support_overview_viewed",
            extra={
                "security_event": SUPPORT_OVERVIEW_VIEWED,
                "user_id": str(operator.id),
                "organization_id": str(organization.id),
            },
        )


def overview(organization: Organization, now: Any) -> list[str]:
    """The lines of the overview, without any of the company's own texts."""
    locales = ", ".join(organization_content_locales(organization))
    lines = [f"Firma {organization.id} · języki: {locales}"]
    effective = effective_mode(organization.id)
    lines.append(
        f"Tryb: {effective.mode} (źródło {effective.source}"
        + (f", powód {effective.reason}" if effective.reason else "")
        + f"; firma: {effective.company_mode} z {effective.company_source})"
    )
    override = operator_override(organization.id)
    if override is not None and (override.mode_cap or override.auto_monthly_limit_cap is not None):
        lines.append(
            f"Nadpisanie operatora: tryb ≤ {override.mode_cap or '—'}, "
            f"limit automatu ≤ {override.auto_monthly_limit_cap}"
        )
    settings_row = TranslationSettings.all_objects.filter(organization=organization).first()
    auto = bool(settings_row and settings_row.auto_changes)
    consent = (
        f"zgoda członkostwa {settings_row.auto_consent_membership_id} "
        f"od {settings_row.auto_consent_at:%Y-%m-%d %H:%M}"
        if settings_row and settings_row.auto_consent_at
        else "bez zgody"
    )
    lines.append(
        f"Automat: {'włączony' if auto else 'wyłączony'}, {consent}; "
        f"limit miesiąca {settings_row.auto_monthly_limit if settings_row else None}, "
        f"zużyte w tym miesiącu {automatic_credits_this_month(organization.id, now)} kredytów; "
        f"publikacja masowa od {mass_publication_cap()} obiektów"
    )
    since = now - timedelta(days=RECENT_DAYS)
    jobs = TranslationJob.all_objects.filter(organization=organization, created_at__gte=since)
    states = Counter(jobs.values_list("state", flat=True))
    lines.append(
        f"Zlecenia z {RECENT_DAYS} dni: {sum(states.values())}"
        + (f" ({_counts(states)})" if states else "")
    )
    for job in jobs.order_by("-created_at")[:10]:
        lines.append(
            f"  {job.id} {job.created_at:%Y-%m-%d %H:%M} {job.trigger} {job.state}"
            f" kredyty {job.credits}" + (f" błąd {job.error_code}" if job.error_code else "")
        )
    for source in sorted(registry.translation_sources(), key=lambda item: item.key):
        items = Counter(
            TranslationJobItem.all_objects.filter(
                organization=organization, source_key=source.key, created_at__gte=since
            ).values_list("state", flat=True)
        )
        review = Counter(
            TranslationReviewItem.all_objects.filter(
                organization=organization, source_key=source.key, state=ReviewState.OPEN
            ).values_list("reason", flat=True)
        )
        waiting = Counter(
            TranslationDemand.all_objects.filter(
                organization=organization,
                source_key=source.key,
                state__in=(DemandState.WAITING, DemandState.BLOCKED),
            ).values_list("reason", flat=True)
        )
        if not (items or review or waiting):
            continue
        lines.append(f"Źródło {source.key}:")
        if items:
            lines.append(f"  pozycje zleceń: {_counts(items)}")
        if review:
            lines.append(f"  czeka na decyzję: {_counts(review)}")
        if waiting:
            lines.append(
                "  popyt automatu: "
                + _counts(Counter({reason or "do terminu": n for reason, n in waiting.items()}))
            )
    return lines


def _counts(counter: Counter[Any]) -> str:
    return ", ".join(f"{key} {count}" for key, count in sorted(counter.items()))
