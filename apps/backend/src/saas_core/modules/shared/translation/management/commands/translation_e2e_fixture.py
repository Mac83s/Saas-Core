"""Atrapa tłumaczeń dla jednej firmy na stacku testów przeglądarkowych (TL15d).

Test przeglądarkowy zamawia tłumaczenie z panelu, a `worker-ai` odpowiada bez
wywołania prawdziwego modelu: każdy fragment wraca jako „[de] tekst źródłowy”.
Dotyczy tylko wskazanej firmy; reszta stacku zostaje przy prawdziwym modelu.

    python manage.py translation_e2e_fixture on --organization <slug> --operator <e-mail>
    python manage.py translation_e2e_fixture off --organization <slug> --operator <e-mail>
    python manage.py translation_e2e_fixture show

Komenda odmawia, dopóki stack nie ma jawnie włączonego `MODEL_PORT_TEST_DOUBLE`
(domyślnie wyłączone; nie wynika z `APP_ENV`). Nie zapisuje modelu, ceny ani
klucza: dopisuje albo usuwa jeden wiersz z listy firm atrapy. `off` cofa `on`
w całości.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from saas_core.modules.core.identity.operators import operator_for_command
from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.pre_tenant import PRE_TENANT_DB
from saas_core.modules.shared.model_port.models import TestDoubleCompany
from saas_core.modules.shared.model_port.test_double import enabled


def _slug(organization_id: UUID) -> str | None:
    """The company's slug, read inside the company itself: the organization
    registry forces row-level security."""
    with transaction.atomic():
        set_local_organization_id(organization_id)
        return (
            Organization.objects.filter(pk=organization_id).values_list("slug", flat=True).first()
        )


class Command(BaseCommand):
    help = "Włącza albo wyłącza atrapę tłumaczeń dla jednej firmy (stack testów przeglądarkowych)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("action", choices=["on", "off", "show"])
        parser.add_argument("--organization", help="Slug firmy testu.")
        parser.add_argument("--operator", help="Adres operatora; is_staff i MFA.")

    def handle(self, *_args: Any, **options: Any) -> None:
        if not enabled():
            raise CommandError(
                "Atrapa tłumaczeń jest wyłączona na tym stacku: ustaw MODEL_PORT_TEST_DOUBLE=true "
                "w środowisku testów przeglądarkowych. Na serwerze z klientami nie ustawiaj."
            )
        if options["action"] == "show":
            rows = list(TestDoubleCompany.objects.order_by("created_at"))
            for row in rows:
                self.stdout.write(
                    f"{row.organization_id}\t{_slug(row.organization_id) or '?'}\t"
                    f"{row.added_by}\t{row.created_at:%Y-%m-%d %H:%M}"
                )
            if not rows:
                self.stdout.write("Żadna firma nie używa atrapy.")
            return
        slug = (options["organization"] or "").strip()
        if not slug:
            raise CommandError("Podaj --organization: slug firmy testu.")
        # ADR-041: finding a company by its slug is a question to the whole
        # registry; the identifier it answers with is all that is kept.
        organization_id = (
            Organization.objects.using(PRE_TENANT_DB)
            .filter(slug=slug)
            .values_list("id", flat=True)
            .first()
        )
        if organization_id is None:
            raise CommandError(f"Nie ma firmy o slugu {slug}.")
        operator = operator_for_command(options["operator"])
        if options["action"] == "on":
            TestDoubleCompany.objects.update_or_create(
                organization_id=organization_id, defaults={"added_by": operator.email}
            )
            self.stdout.write(f"{slug}: tłumaczy atrapa.")
        else:
            TestDoubleCompany.objects.filter(organization_id=organization_id).delete()
            self.stdout.write(f"{slug}: tłumaczy prawdziwy model.")
