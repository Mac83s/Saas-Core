"""Potwierdzenie zlecenia tłumaczenia treści platformy ponad próg (ADR-069 pkt 26).

Treść obszaru platformy (np. Puppily) płaci budżet USD wdrożenia, nie kredyty;
zlecenie wycenione ponad próg czeka na operatora. Wymaga konta is_staff z MFA
i powodu; zostawia wpis w historii.

    python manage.py translation_confirm_job --organization <uuid> --job <uuid> \\
        --operator <e-mail> --reason "…"
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from saas_core.modules.core.organizations.audit import record_audit

from ..operator import operator_user, reason_of
from ._job_command import locked_job, uuid_of

logger = logging.getLogger("saas_core.security")


class Command(BaseCommand):
    help = "Potwierdza zlecenie tłumaczenia treści platformy ponad próg budżetu."

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
            if not job.confirmation_required or job.confirmed_at is not None:
                raise CommandError("To zlecenie nie czeka na potwierdzenie.")
            job.confirmed_at = timezone.now()
            job.confirmed_by = operator
            job.next_attempt_at = job.confirmed_at
            job.save(
                update_fields=["confirmed_at", "confirmed_by", "next_attempt_at", "updated_at"]
            )
            record_audit(
                organization=organization,
                action="translation.job_confirmed",
                actor=operator,
                target_type="translation.job",
                target_id=job.id,
                metadata={
                    "job_id": str(job.id),
                    "estimated_usd_micros": job.estimated_usd_micros,
                    "reason": reason,
                },
            )
            organization_id, job_id = organization.id, job.id

            def enqueue() -> None:
                from ...tasks import enqueue_job

                enqueue_job(organization_id, job_id)

            transaction.on_commit(enqueue, robust=True)
        logger.warning(
            "translation_job_confirmed",
            extra={
                "security_event": "translation.job_confirmed",
                "user_id": str(operator.id),
                "job_id": str(job_id),
            },
        )
        self.stdout.write(self.style.SUCCESS("Zlecenie potwierdzone."))
