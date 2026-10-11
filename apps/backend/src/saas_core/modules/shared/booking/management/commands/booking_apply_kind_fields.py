"""Give services that exist the form fields their kind of visit brings.

A module's descriptor may declare booking-form fields for a kind of visit it
owns (`appointmentKindFields`); they are copied onto a service when it is made.
This is for the services made before the module declared them. Without
`--apply` it only says what it would add. A service that already has a field
of that name — switched on or off — keeps it untouched, so repeating the run
adds nothing. Nothing is changed or deleted, only added.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.tenant_scope import billing_organization_ids
from saas_core.modules.shared.booking.form_fields import (
    _first_label,
    copy_kind_fields,
    kind_fields_refusal,
    missing_kind_fields,
)
from saas_core.modules.shared.booking.models import Service

#: The role the command's writes are signed with; it holds no permission, and
#: its audit rows name no person (the system did it).
SYSTEM_ROLE = "booking_kind_fields"


def _system_context(organization_id: UUID) -> TenantContext:
    return TenantContext(
        organization_id=organization_id,
        membership_id=organization_id,
        actor_id=organization_id,
        role_key=SYSTEM_ROLE,
        permissions=frozenset(),
        principal_kind="service",
    )


def _code(error: ValidationError) -> str:
    codes = error.get_codes()
    flat = [c for value in codes.values() for c in value] if isinstance(codes, dict) else codes
    return str(flat[0]) if flat else "invalid"


class Command(BaseCommand):
    help = (
        "Dodaje usługom pola formularza, które deklaruje ich typ wizyty "
        "(appointmentKindFields). Bez --apply tylko wypisuje, co by dodał."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--apply", action="store_true", help="Zapisz zmiany.")
        parser.add_argument("--organization", help="Tylko ta firma (UUID).")

    def handle(self, *args: Any, **options: Any) -> None:
        apply = bool(options["apply"])
        if not settings.APPOINTMENT_KIND_FIELDS:
            self.stdout.write("Żaden moduł nie deklaruje pól dla typów wizyty.")
            return
        if options["organization"]:
            try:
                only = [UUID(options["organization"])]
            except ValueError as error:
                raise CommandError("--organization wymaga UUID firmy.") from error
        else:
            only = billing_organization_ids()
        services = added = refused = 0
        for organization_id in only:
            seen, new, no = self._organization(organization_id, apply)
            services += seen
            added += new
            refused += no
        self.stdout.write(f"Usługi: {services}, dodane pola: {added}, odmowy: {refused}.")
        if refused:
            raise CommandError(f"Odmowy: {refused} (usługi opisane wyżej, reszta przeszła).")

    def _organization(self, organization_id: UUID, apply: bool) -> tuple[int, int, int]:
        # One transaction per company, the tenant set before its first tenant
        # read (a read before it answers nothing under RLS).
        with transaction.atomic():
            set_local_organization_id(organization_id)
            organization = Organization.objects.filter(pk=organization_id).first()
            if organization is None:
                raise CommandError(f"Firma {organization_id} nie istnieje.")
            context = _system_context(organization_id)
            services = added = refused = 0
            with activate_tenant_context(context):
                for service in Service.all_objects.filter(
                    organization=organization,
                    appointment_kind__in=list(settings.APPOINTMENT_KIND_FIELDS),
                ).order_by("created_at", "id"):
                    made: list[str] = []
                    missing = missing_kind_fields(organization, service)
                    reason = kind_fields_refusal(organization, service, missing) if missing else None
                    if reason is None and apply:
                        # A savepoint per service: a refusal leaves the others alone.
                        try:
                            with transaction.atomic():
                                made = [
                                    f.name for f in copy_kind_fields(context, organization, service)
                                ]
                        except ValidationError as error:
                            reason = _code(error)
                    if reason is not None:
                        refused += 1
                        self.stdout.write(f"{organization.slug}: {service.name}: odmowa ({reason})")
                        continue
                    if not apply:
                        made = [_first_label(organization, given["labels"]) for given in missing]
                    if made:
                        services += 1
                        added += len(made)
                        verb = "dodano" if apply else "dodałbym"
                        self.stdout.write(
                            f"{organization.slug}: {service.name}: {verb} {', '.join(made)}"
                        )
            return services, added, refused
