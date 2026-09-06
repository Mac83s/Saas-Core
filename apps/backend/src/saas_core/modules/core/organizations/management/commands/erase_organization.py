"""Erase one tenant, on purpose, with a name and a reason (ADR-042).

An operation this irreversible does not get a convenient interface. It is a
command an operator runs, it names the organization, it demands a reason, and it
does nothing at all until `--apply` — because the version of this that is easy
to run by accident is the version that eventually is.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from saas_core.modules.core.identity.mfa import has_confirmed_mfa
from saas_core.modules.core.identity.models import User

from ...erasure import (
    ErasureBlocked,
    erase_organization,
    erasure_is_complete,
    row_counts,
    stored_object_keys,
)
from ...models import Organization
from ...pre_tenant import PRE_TENANT_DB


class Command(BaseCommand):
    help = (
        "Usuwa organizację razem z jej danymi (ADR-042). Domyślnie tylko "
        "wypisuje, co zniknie; usuwa dopiero z --apply."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--organization", required=True, help="Identyfikator organizacji.")
        parser.add_argument(
            "--operator",
            required=True,
            help="Adres operatora zlecającego usunięcie; wymaga is_staff i MFA.",
        )
        parser.add_argument(
            "--reason",
            required=True,
            help="Dlaczego. Trafia do pokwitowania i jest jedynym śladem po operacji.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Wykonaj usunięcie zamiast wypisania planu.",
        )
        parser.add_argument(
            "--confirm",
            default="",
            help="Slug organizacji przepisany ręcznie. Wymagany razem z --apply.",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        operator = self._operator(str(options["operator"]))
        try:
            organization_id = UUID(str(options["organization"]))
        except (TypeError, ValueError) as error:
            raise CommandError("Nieprawidłowy identyfikator organizacji.") from error

        # ADR-041: which organization this is, is a question about the registry,
        # asked before any tenant is set.
        organization = (
            Organization.objects.using(PRE_TENANT_DB).filter(pk=organization_id).first()
        )
        if organization is None:
            raise CommandError("Organizacja nie istnieje.")

        reason = str(options["reason"]).strip()
        if len(reason) < 10:
            raise CommandError("Powód musi być zdaniem, nie słowem.")

        counts = row_counts(organization_id)
        keys = stored_object_keys(organization_id)
        self.stdout.write(f"organizacja {organization.slug} ({organization.name}):")
        for label, found in sorted(counts.items()):
            self.stdout.write(f"    {label}: {found}")
        self.stdout.write(f"    obiekty w storage: {len(keys)}")

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING("Plan bez zmian. Uruchom ponownie z --apply.")
            )
            return
        if str(options["confirm"]) != organization.slug:
            raise CommandError(
                "Przepisz slug organizacji w --confirm; to jedyny moment, w którym "
                "można się rozmyślić."
            )

        try:
            receipt = erase_organization(
                organization=organization, requested_by=operator, reason=reason
            )
        except ErasureBlocked as error:
            raise CommandError(str(error)) from error

        state = erasure_is_complete(organization_id)
        self.stdout.write(self.style.SUCCESS(f"pokwitowanie {receipt.id}"))
        self.stdout.write(json.dumps(state, indent=2, ensure_ascii=False, default=str))
        if state["rows"] or state["organization"]:
            raise CommandError("Po usunięciu zostały wiersze — to jest błąd, nie ostrzeżenie.")
        if receipt.pending_object_keys:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(receipt.pending_object_keys)} obiektów czeka na skasowanie "
                    "przez przemiatanie mediów."
                )
            )

    def _operator(self, email: str) -> User:
        normalized = User.objects.normalize_email(email)
        operator = User.objects.filter(email=normalized).first()
        if operator is None or not operator.is_active:
            raise CommandError(f"Operator {normalized} nie istnieje albo jest nieaktywny.")
        if not operator.is_staff:
            raise CommandError(f"Operator {normalized} nie ma uprawnień operatorskich.")
        if not has_confirmed_mfa(operator):
            # The one irreversible operation in the product asks for the second
            # factor, not because policy says so but because a stolen password
            # would otherwise be enough to erase a customer.
            raise CommandError(f"Operator {normalized} musi mieć potwierdzone MFA.")
        return operator
