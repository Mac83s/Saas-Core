"""Włącz albo wyłącz widoczne oznaczenie obrazów AI na stronach (ADR-059 pkt 7).

Przełącznik dotyczy całego deploymentu i wyłącznie odznaki „AI” oraz dopisku w
`alt`. Znacznik XMP w plikach zostaje zawsze. Za przejrzystość z art. 50 AI Act
odpowiada operator, więc zmiana wymaga operatora z is_staff i potwierdzonym MFA,
powodu i zostawia wiersz historii — nawet gdy stan się nie zmienia.

    python manage.py set_ai_badge --operator <e-mail> --off --reason "…"
    python manage.py set_ai_badge --operator <e-mail> --on --reason "…"
    python manage.py set_ai_badge --show
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from saas_core.modules.core.identity.mfa import has_confirmed_mfa
from saas_core.modules.core.identity.models import User

from ...ai_badge import badge_visible
from ...models import AiBadgeSwitch

logger = logging.getLogger("saas_core.security")


class Command(BaseCommand):
    help = "Włącza albo wyłącza odznakę „AI” na obrazach AI na stronach klientów."

    def add_arguments(self, parser: CommandParser) -> None:
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--on", action="store_true", help="Pokazuj odznakę (domyślnie).")
        mode.add_argument("--off", action="store_true", help="Ukryj odznakę; XMP zostaje.")
        mode.add_argument("--show", action="store_true", help="Stan i 10 ostatnich zmian.")
        parser.add_argument("--operator", help="Adres operatora; is_staff i MFA.")
        parser.add_argument("--reason", help="Dlaczego zmieniamy. Trafia do historii.")

    def handle(self, *_args: Any, **options: Any) -> None:
        if options["show"]:
            self._show()
            return
        if not options["operator"]:
            raise CommandError("Podaj --operator.")
        reason = (options["reason"] or "").strip()
        if not reason:
            raise CommandError("Podaj --reason: dlaczego zmieniamy oznaczenie.")
        operator = self._operator(options["operator"])
        visible = bool(options["on"])
        AiBadgeSwitch.objects.create(visible=visible, reason=reason, changed_by=operator)
        # The reason stays in the table; logs carry who and what, never why.
        logger.warning(
            "sites_ai_badge_switched",
            extra={
                "security_event": "sites.ai_badge_switched",
                "user_id": str(operator.id),
                "visible": visible,
            },
        )
        state = "włączona" if visible else "wyłączona (XMP w plikach zostaje)"
        self.stdout.write(self.style.SUCCESS(f"Odznaka AI: {state}."))

    def _show(self) -> None:
        state = "włączona" if badge_visible() else "wyłączona"
        self.stdout.write(f"Odznaka AI: {state}.")
        rows = AiBadgeSwitch.objects.select_related("changed_by").order_by("-created_at", "-id")
        for row in rows[:10]:
            self.stdout.write(
                f"{row.created_at:%Y-%m-%d %H:%M:%S%z}  "
                f"{'on ' if row.visible else 'off'}  {row.changed_by.email}  {row.reason}"
            )

    def _operator(self, email: str) -> User:
        normalized = User.objects.normalize_email(email)
        operator = User.objects.filter(email=normalized).first()
        if operator is None or not operator.is_active:
            raise CommandError(f"Operator {normalized} nie istnieje albo jest nieaktywny.")
        if not operator.is_staff:
            raise CommandError(f"Operator {normalized} nie ma uprawnień operatorskich.")
        if not has_confirmed_mfa(operator):
            raise CommandError(f"Operator {normalized} musi mieć potwierdzone MFA.")
        return operator
