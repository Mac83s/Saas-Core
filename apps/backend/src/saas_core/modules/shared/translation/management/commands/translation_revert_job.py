"""Cofnięcie zlecenia tłumaczenia przez operatora (ADR-069 pkt 22).

Każde źródło, które zlecenie zapisało, wraca do tekstów sprzed niego — przez
własną publikację pochodną. Kredyty nie wracają same: zwrot to osobna,
audytowana korekta operatora. Wymaga konta is_staff z MFA i powodu.

    python manage.py translation_revert_job --organization <uuid> --job <uuid> \\
        --operator <e-mail> --reason "…"
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from saas_core.content_protocol.registry import translation_source
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import activate_tenant_context

from ...models import ItemState, TranslationJobItem
from ...worker import job_context
from ..operator import operator_user, reason_of
from ._job_command import locked_job, uuid_of

logger = logging.getLogger("saas_core.security")


class Command(BaseCommand):
    help = "Cofa zlecenie tłumaczenia: źródła wracają do tekstów sprzed niego."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--organization", required=True)
        parser.add_argument("--job", required=True)
        parser.add_argument("--operator", required=True, help="Adres operatora; is_staff i MFA.")
        parser.add_argument("--reason", help="Dlaczego. Trafia do historii.")

    def handle(self, *_args: Any, **options: Any) -> None:
        reason = reason_of(options["reason"])
        operator = operator_user(options["operator"])
        with transaction.atomic():
            organization, job = locked_job(
                uuid_of(options["organization"], "organizacji"), uuid_of(options["job"], "zlecenia")
            )
            if job.reverted_at is not None:
                raise CommandError("To zlecenie zostało już cofnięte.")
            # The sources check the right to publish: the job's own person, as
            # the job ran, takes the texts back.
            context = job_context(job)
            if context is None:
                raise CommandError(
                    "Osoba, która zleciła tłumaczenie, nie ma już dostępu — cofnij w panelu firmy."
                )
            sources = sorted(
                set(
                    TranslationJobItem.all_objects.filter(
                        job=job, state=ItemState.WRITTEN
                    ).values_list("source_key", flat=True)
                )
            )
            restored = 0
            with activate_tenant_context(context):
                for source_key in sources:
                    restored += len(
                        translation_source(source_key).revert(
                            context=context,
                            job_ref=f"translation_job:{job.id}",
                            idempotency_key=f"revert:{job.id}:{source_key}",
                        )
                    )
            job.reverted_at = timezone.now()
            job.save(update_fields=["reverted_at", "updated_at"])
            record_audit(
                organization=organization,
                action="translation.job_reverted",
                actor=operator,
                target_type="translation.job",
                target_id=job.id,
                metadata={
                    "job_id": str(job.id),
                    "sources": sources,
                    "restored": restored,
                    "reason": reason,
                },
            )
        logger.warning(
            "translation_job_reverted",
            extra={
                "security_event": "translation.job_reverted",
                "user_id": str(operator.id),
                "job_id": str(job.id),
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Cofnięto zlecenie ({restored} pozycji)."))
