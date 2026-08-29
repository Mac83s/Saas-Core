"""Issues a content automation grant for one API credential.

An operator action, not a customer one (ADR-035 §4): the customer buys the
service and receives its effect; they do not configure the integration, never
see the secret, and cannot widen what it may touch. A grant issued here is the
only thing that turns an authenticated key into a key that may do something.

Running it again for the same credential and resource replaces the grant's
bounds rather than stacking a second one, so tightening a limit is one command
and not an archaeology exercise.
"""

from __future__ import annotations

import datetime
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from saas_core.modules.core.identity.mfa import has_confirmed_mfa
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import (
    Organization,
    WorkspaceKind,
)
from saas_core.modules.shared.notifications.models import ApiKey
from saas_core.modules.shared.sites.models import (
    AutomationGrantMode,
    ContentAutomationGrant,
    ContentCollection,
    Site,
)

GRANT_ISSUED = "sites.automation_grant.issued"


class Command(BaseCommand):
    help = "Nadaje grant automatyzacji treści dla wskazanego klucza API."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--operator", required=True, help="E-mail operatora.")
        parser.add_argument("--api-key", required=True, help="Identyfikator klucza.")
        parser.add_argument("--site", help="Identyfikator site'u objętego grantem.")
        parser.add_argument("--collection", help="Identyfikator kolekcji.")
        parser.add_argument(
            "--mode",
            required=True,
            choices=list(AutomationGrantMode.values),
            help="Tryb grantu.",
        )
        parser.add_argument("--expires-in-days", type=int)
        parser.add_argument("--max-changes-per-day", type=int)
        parser.add_argument("--max-payload-bytes", type=int)
        parser.add_argument("--window", help="Okno w formacie HH:MM-HH:MM.")
        parser.add_argument(
            "--allow-link-host",
            action="append",
            default=[],
            help="Host, do którego automatyzacja może linkować. Powtarzalny.",
        )

    @transaction.atomic
    def handle(self, *_args: Any, **options: Any) -> None:
        operator = self._operator(str(options["operator"]))
        key = ApiKey.all_objects.filter(pk=self._uuid(options["api_key"], "klucza")).first()
        if key is None:
            raise CommandError("Klucz API nie istnieje.")

        site, collection = self._target(options, organization_id=key.organization_id)
        mode = str(options["mode"])
        expires_at = (
            timezone.now() + datetime.timedelta(days=int(options["expires_in_days"]))
            if options["expires_in_days"]
            else None
        )
        window_start, window_end = self._window(options.get("window"))

        if mode == AutomationGrantMode.AUTONOMOUS:
            # ADR-035 §4: autonomy is bounded by the grant's fields, not by its
            # name. The database refuses an unbounded one, and saying so here
            # is friendlier than a constraint violation.
            if not (
                options["max_changes_per_day"]
                and options["max_payload_bytes"]
                and expires_at
            ):
                raise CommandError(
                    "Tryb autonomous wymaga --expires-in-days, "
                    "--max-changes-per-day i --max-payload-bytes."
                )
            if not Organization.objects.filter(
                pk=key.organization_id, workspace_kind=WorkspaceKind.PLATFORM
            ).exists():
                raise CommandError(
                    "Tryb autonomous jest na razie dopuszczony wyłącznie "
                    "w workspace platformowym."
                )

        grant, created = ContentAutomationGrant.all_objects.update_or_create(
            organization_id=key.organization_id,
            credential_id=key.id,
            site=site,
            collection=collection,
            defaults={
                "mode": mode,
                "expires_at": expires_at,
                "max_changes_per_day": options["max_changes_per_day"],
                "max_payload_bytes": options["max_payload_bytes"],
                "window_start": window_start,
                "window_end": window_end,
                "allowed_link_hosts": list(options["allow_link_host"]),
                "revoked_at": None,
                "created_by": operator,
            },
        )
        record_audit(
            organization=Organization.objects.get(pk=key.organization_id),
            action=GRANT_ISSUED,
            actor=operator,
            target_type="content_automation_grant",
            target_id=grant.id,
            metadata={
                "mode": mode,
                "credential_id": str(key.id),
                "site_id": str(site.id) if site else None,
                "collection_id": str(collection.id) if collection else None,
            },
        )
        self.stdout.write(
            f"{'Nadano' if created else 'Zaktualizowano'} grant {grant.id}: "
            f"tryb {mode}, wygasa {expires_at or 'nigdy'}."
        )

    def _operator(self, email: str) -> User:
        operator = User.objects.filter(email=email, is_staff=True).first()
        if operator is None:
            raise CommandError("Operator musi być kontem staff.")
        if not has_confirmed_mfa(operator):
            # The same bar as entering the platform workspace: issuing a grant
            # is how an automation gets the right to change a customer's site.
            raise CommandError("Operator musi mieć potwierdzone MFA.")
        return operator

    def _target(
        self, options: dict[str, Any], *, organization_id: Any
    ) -> tuple[Site | None, ContentCollection | None]:
        raw_site = options.get("site")
        raw_collection = options.get("collection")
        if bool(raw_site) == bool(raw_collection):
            raise CommandError("Podaj dokładnie jedno: --site albo --collection.")
        if raw_site:
            site = Site.all_objects.filter(
                pk=self._uuid(raw_site, "site'u"), organization_id=organization_id
            ).first()
            if site is None:
                raise CommandError("Site nie należy do organizacji tego klucza.")
            return site, None
        collection = ContentCollection.all_objects.filter(
            pk=self._uuid(raw_collection, "kolekcji"), organization_id=organization_id
        ).first()
        if collection is None:
            raise CommandError("Kolekcja nie należy do organizacji tego klucza.")
        return None, collection

    def _window(self, raw: str | None) -> tuple[datetime.time | None, datetime.time | None]:
        if not raw:
            return None, None
        try:
            start, end = (part.strip() for part in str(raw).split("-", 1))
            return (
                datetime.time.fromisoformat(start),
                datetime.time.fromisoformat(end),
            )
        except ValueError as error:
            raise CommandError("Okno musi mieć postać HH:MM-HH:MM.") from error

    def _uuid(self, raw: Any, what: str) -> UUID:
        try:
            return UUID(str(raw))
        except (TypeError, ValueError) as error:
            raise CommandError(f"Nieprawidłowy identyfikator {what}.") from error
