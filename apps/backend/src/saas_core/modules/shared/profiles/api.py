"""Public use-case API of the Profiles module.

Another module that has to name the company to someone outside it (a report's
header, a copy of an e-mail) asks here instead of reading the private models.
"""

from __future__ import annotations

from uuid import UUID

from saas_core.modules.core.organizations.models import BillingProfile, Organization

from .models import ProfileSubjectKind, PublicProfile


def organization_contact(organization_id: UUID) -> dict[str, str]:
    """Name, city, phone and e-mail the company shows; missing pieces are "".

    The public company profile says how the company presents itself; the city
    falls back to the billing address, the name to the organization's own.
    """
    profile = PublicProfile.all_objects.filter(
        organization_id=organization_id, subject_kind=ProfileSubjectKind.ORGANIZATION
    ).first()
    organization = Organization.objects.get(pk=organization_id)
    billing = BillingProfile.objects.filter(organization_id=organization_id).first()
    return {
        "name": (profile.display_name if profile else "") or organization.name,
        "city": billing.city if billing else "",
        "phone": profile.contact_phone if profile else "",
        "email": (profile.contact_email if profile else "")
        or (billing.billing_email if billing else ""),
    }


__all__ = ["organization_contact"]
