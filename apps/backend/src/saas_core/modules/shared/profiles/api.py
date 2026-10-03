"""Public use-case API of the Profiles module.

Another module that has to name the company to someone outside it (a report's
header, a copy of an e-mail) asks here instead of reading the private models.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.organizations.models import BillingProfile, Organization

from .models import ProfileSubjectKind, PublicProfile
from .search_index import catalog_changed, register_catalog_terms


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


def business_card_contact(organization_id: UUID) -> tuple[str, str]:
    """The phone and e-mail the company's business card shows — only what it
    chose to show, never the billing e-mail, because a website is public."""
    profile = PublicProfile.all_objects.filter(
        organization_id=organization_id, subject_kind=ProfileSubjectKind.ORGANIZATION
    ).first()
    return (profile.contact_phone, profile.contact_email) if profile else ("", "")


def business_card_sender(organization_id: UUID) -> tuple[str, str]:
    """The name and e-mail the company's business card shows ("" where it
    shows none) — whom its customers' mail comes from and a reply goes to."""
    profile = PublicProfile.all_objects.filter(
        organization_id=organization_id, subject_kind=ProfileSubjectKind.ORGANIZATION
    ).first()
    return (profile.display_name, profile.contact_email) if profile else ("", "")


def _saved(profile: PublicProfile) -> PublicProfile:
    try:
        profile.full_clean(exclude=["organization"], validate_unique=False)
    except DjangoValidationError as error:
        raise ValidationError({"name": error.messages}) from error
    profile.save()
    return profile


def create_person_profile(
    organization_id: UUID, *, name: str, membership_id: UUID | None
) -> PublicProfile:
    """A person the company shows its customers, made by the calendar's
    „Pokazuj klientom” (ADR-036 §4, ADR-058 §8). The caller has authorized
    the action; this module keeps what a person profile is."""
    return _saved(
        PublicProfile(
            organization_id=organization_id,
            subject_kind=ProfileSubjectKind.PERSON,
            display_name=name,
            membership_id=membership_id,
        )
    )


def rename_person_profile(organization_id: UUID, profile_id: UUID, *, name: str) -> None:
    profile = PublicProfile.all_objects.get(
        organization_id=organization_id, pk=profile_id, subject_kind=ProfileSubjectKind.PERSON
    )
    if profile.display_name != name:
        profile.display_name = name
        profile.version += 1
        _saved(profile)


def remove_person_profile(organization_id: UUID, profile_id: UUID) -> None:
    """Turning „Pokazuj klientom” off: the name leaves the public side."""
    PublicProfile.all_objects.filter(
        organization_id=organization_id, pk=profile_id, subject_kind=ProfileSubjectKind.PERSON
    ).delete()


def person_names(organization_id: UUID, profile_ids: Iterable[UUID | None]) -> dict[UUID, str]:
    """The names people are shown to customers under, by profile."""
    wanted = {profile_id for profile_id in profile_ids if profile_id is not None}
    if not wanted:
        return {}
    return dict(
        PublicProfile.all_objects.filter(
            organization_id=organization_id,
            pk__in=wanted,
            subject_kind=ProfileSubjectKind.PERSON,
        ).values_list("id", "display_name")
    )


__all__ = [
    "catalog_changed",
    "create_person_profile",
    "business_card_contact",
    "organization_contact",
    "person_names",
    "register_catalog_terms",
    "remove_person_profile",
    "rename_person_profile",
]
