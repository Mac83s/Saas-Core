"""Nadpisanie operatora dla jednej firmy (ADR-069 pkt 30, ADR-078 pkt 3 — źródło `operator`).

Wstrzymanie (`--mode-cap off`), wymuszony przegląd (`--mode-cap review`), niższy
limit automatu (`--auto-limit N`); `--clear` zdejmuje nadpisanie. Działa jak
blokada: wygrywa z wartością firmy, a firma widzi pole zablokowane z powodem.
Każda zmiana to nowy wiersz i wpis w historii firmy.

    python manage.py translation_org_override --organization <uuid> --operator <e-mail> \\
        --mode-cap off --reason "…"
    python manage.py translation_org_override --organization <uuid> --show
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.models import Organization

from ...models import TranslationOverride
from ..operator import operator_user, reason_of

logger = logging.getLogger("saas_core.security")


class Command(BaseCommand):
    help = "Wstrzymuje, wymusza przegląd albo obniża limit automatu tłumaczeń jednej firmy."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--organization", required=True, help="Identyfikator organizacji.")
        parser.add_argument("--mode-cap", choices=["review", "off"])
        parser.add_argument("--auto-limit", type=int, help="Najwyżej tyle kredytów automatu.")
        parser.add_argument("--clear", action="store_true", help="Zdejmij nadpisanie.")
        parser.add_argument("--show", action="store_true", help="10 ostatnich zmian.")
        parser.add_argument("--operator", help="Adres operatora; is_staff i MFA.")
        parser.add_argument("--reason", help="Dlaczego. Firma widzi go przy zablokowanym polu.")

    @transaction.atomic
    def handle(self, *_args: Any, **options: Any) -> None:
        try:
            organization_id = UUID(str(options["organization"]))
        except ValueError:
            raise CommandError("Nieprawidłowy identyfikator organizacji.") from None
        # The override table forces row-level security: the command works
        # inside the organization the operator names.
        set_local_organization_id(organization_id)
        organization = Organization.objects.filter(pk=organization_id).first()
        if organization is None:
            raise CommandError("Organizacja nie istnieje.")
        if options["show"]:
            rows = TranslationOverride.all_objects.filter(organization=organization)
            for row in rows.select_related("changed_by")[:10]:
                limit = row.auto_monthly_limit_cap
                self.stdout.write(
                    f"{row.created_at:%Y-%m-%d %H:%M:%S%z}  mode_cap={row.mode_cap or '-'}  "
                    f"auto_limit={limit if limit is not None else '-'}  "
                    f"{row.changed_by.email}  {row.reason}"
                )
            return
        cleared = bool(options["clear"])
        if cleared == bool(options["mode_cap"] or options["auto_limit"] is not None):
            raise CommandError("Podaj --mode-cap i/lub --auto-limit albo samo --clear.")
        if options["auto_limit"] is not None and options["auto_limit"] < 0:
            raise CommandError("--auto-limit nie może być ujemny.")
        if not options["operator"]:
            raise CommandError("Podaj --operator.")
        reason = reason_of(options["reason"])
        operator = operator_user(options["operator"])
        row = TranslationOverride.all_objects.create(
            organization=organization,
            mode_cap="" if cleared else (options["mode_cap"] or ""),
            auto_monthly_limit_cap=None if cleared else options["auto_limit"],
            reason=reason,
            changed_by=operator,
        )
        record_audit(
            organization=organization,
            action="translation.operator_override",
            actor=operator,
            target_type="translation.settings",
            target_id=row.id,
            metadata={
                "mode_cap": row.mode_cap,
                "auto_monthly_limit_cap": row.auto_monthly_limit_cap,
                "cleared": cleared,
            },
        )
        logger.warning(
            "translation_org_override_set",
            extra={
                "security_event": "translation.org_override_set",
                "user_id": str(operator.id),
                "organization_id": str(organization.id),
                "mode_cap": row.mode_cap,
            },
        )
        self.stdout.write(self.style.SUCCESS("Nadpisanie zapisane."))
