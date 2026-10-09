"""Brings a body of existing content into one company's site (ADR-079 pkt 34).

    python manage.py sites_import_content document.json \\
        --organization <uuid> --operator <e-mail>            # a dry run: writes nothing
    python manage.py sites_import_content document.json \\
        --organization <uuid> --operator <e-mail> --apply    # the import
    python manage.py sites_import_content --schema           # the document's JSON Schema

The operator names the organization by its id, and the document names it by
its slug: the two must be the same organization, or nothing is read further.
The organization's site is taken when it has exactly one; with more, `--site`
says which. Everything is written as the operator — an operator's account
(staff, two-factor sign-in) with an active membership of that organization —
through the services the panel calls, so the history names them and every
guard a person meets applies.

Without `--apply` the command plans and prints what it would do. Pictures
are read from beside the document. Exit code: 0 — nothing refused; 1 — some
object was refused (the report says which and why; the others are in, or
would be); 2 — the document or the target is wrong and nothing was done.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from saas_core.modules.core.identity.mfa import has_confirmed_mfa
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import Membership, MembershipStatus

from ...content_import import ImportStopped, format_report, run_import
from ...content_import_schema import DOCUMENT_SCHEMA
from ...permissions import SITE_CONTENT_EDIT, SITE_PUBLISH


class Command(BaseCommand):
    help = (
        "Wnosi treść z dokumentu content-import.v1 do strony jednej firmy. Bez --apply "
        "tylko planuje i wypisuje raport."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("document", nargs="?", type=Path, help="Dokument JSON (UTF-8).")
        parser.add_argument("--organization", help="Identyfikator (UUID) organizacji.")
        parser.add_argument("--operator", help="E-mail osoby, która wykonuje import.")
        parser.add_argument("--site", help="Identyfikator strony, gdy organizacja ma ich kilka.")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Zapisuje. Bez tej flagi komenda niczego nie zapisuje (przebieg próbny).",
        )
        parser.add_argument(
            "--overwrite-edits",
            action="append",
            default=[],
            metavar="ENTRY_ID",
            help="Wpis (id z dokumentu), którego pola zmienione w panelu po wcześniejszym "
            "imporcie dokument może nadpisać. Powtarzalne.",
        )
        parser.add_argument(
            "--report", type=Path, help="Zapisuje pełny raport jako JSON do tego pliku."
        )
        parser.add_argument(
            "--schema", action="store_true", help="Wypisuje schemat dokumentu i kończy."
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        if options["schema"]:
            self.stdout.write(json.dumps(DOCUMENT_SCHEMA, ensure_ascii=False, indent=2))
            return
        path: Path | None = options["document"]
        if path is None or not options["organization"] or not options["operator"]:
            raise CommandError("Podaj dokument, --organization i --operator.", returncode=2)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CommandError(f"Nie można odczytać {path}: {error}", returncode=2) from error
        organization_id = self._uuid(options["organization"], "organizacji")
        site_id = self._uuid(options["site"], "strony") if options["site"] else None
        context = self._context(organization_id, str(options["operator"]))
        try:
            with activate_tenant_context(context):
                report = run_import(
                    document,
                    base_dir=path.parent,
                    site_id=site_id,
                    dry_run=not options["apply"],
                    overwrite_edits=[str(item) for item in options["overwrite_edits"]],
                )
        except ImportStopped as stopped:
            raise CommandError(
                "Import zatrzymany, nic nie zapisano:\n  " + "\n  ".join(stopped.problems),
                returncode=2,
            ) from stopped
        self.stdout.write(format_report(report))
        if options["report"]:
            options["report"].write_text(
                json.dumps(report.as_dict(), ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        if report.failed:
            raise CommandError("Część obiektów odrzucona — patrz raport.", returncode=1)

    def _uuid(self, value: Any, what: str) -> UUID:
        try:
            return UUID(str(value))
        except (TypeError, ValueError) as error:
            raise CommandError(f"Nieprawidłowy identyfikator {what}.", returncode=2) from error

    def _context(self, organization_id: UUID, email: str) -> Any:
        """The operator's own membership of the organization: its role's
        rights, nothing more. Read as that tenant — memberships force
        row-level security, and the organization is named, never looked up."""
        operator = User.objects.filter(
            email=User.objects.normalize_email(email), is_active=True
        ).first()
        if operator is None:
            raise CommandError(f"Nie ma aktywnego konta {email}.", returncode=2)
        # As the other operator commands of the sites: the history will name
        # this person, so it is somebody who may act for the platform and
        # signs in with two factors — not whoever's address was at hand.
        if not operator.is_staff:
            raise CommandError(f"{email} nie ma uprawnień operatorskich.", returncode=2)
        if not has_confirmed_mfa(operator):
            raise CommandError(f"{email} musi mieć potwierdzone MFA.", returncode=2)
        with transaction.atomic():
            set_local_organization_id(organization_id)
            membership = (
                Membership.objects.select_related("organization", "role")
                .filter(
                    organization_id=organization_id, user=operator, status=MembershipStatus.ACTIVE
                )
                .first()
            )
            if membership is None:
                raise CommandError(
                    "Ta osoba nie ma aktywnego członkostwa w tej organizacji (albo organizacja "
                    "nie istnieje).",
                    returncode=2,
                )
            context = context_from_membership(membership)
        missing = [
            permission
            for permission in (SITE_CONTENT_EDIT, SITE_PUBLISH)
            if not context.has_permission(permission)
        ]
        if missing:
            raise CommandError(
                f"Rola tej osoby nie ma uprawnień: {', '.join(missing)}.", returncode=2
            )
        return context
