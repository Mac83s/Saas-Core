"""What the operator's job commands share: the organization they name, the job."""

from __future__ import annotations

from uuid import UUID

from django.core.management.base import CommandError

from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.models import Organization

from ...models import TranslationJob


def uuid_of(value: object, what: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError:
        raise CommandError(f"Nieprawidłowy identyfikator {what}.") from None


def locked_job(organization_id: UUID, job_id: UUID) -> tuple[Organization, TranslationJob]:
    """Inside the organization the operator names: its tables force RLS."""
    set_local_organization_id(organization_id)
    organization = Organization.objects.filter(pk=organization_id).first()
    if organization is None:
        raise CommandError("Organizacja nie istnieje.")
    job = (
        TranslationJob.all_objects.select_for_update()
        .filter(organization=organization, pk=job_id)
        .first()
    )
    if job is None:
        raise CommandError("Zlecenie nie istnieje w tej organizacji.")
    return organization, job
