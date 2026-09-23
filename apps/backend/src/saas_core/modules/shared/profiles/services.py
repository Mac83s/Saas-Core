"""Everything a profile can have done to it, with the tenant already decided.

The views validate shape; these decide who may act and what it means. Same
reason as everywhere else in this repository: a management command and a task
must be able to reach the rule without going through HTTP.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from rest_framework.exceptions import APIException, NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import (
    audit_snapshot,
    field_changes,
    record_audit,
)
from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.models import (
    Membership,
    MembershipStatus,
    Organization,
    OrganizationAuditAction,
)
from saas_core.modules.core.organizations.permissions import ORGANIZATION_READ
from saas_core.modules.shared.media.models import MediaAsset

from .catalog import validate_placement
from .models import ProfileSubjectKind, PublicProfile, PublicProfileTranslation
from .permissions import PROFILES_MANAGE

EDITABLE_FIELDS = (
    "display_name",
    "headline",
    "bio",
    "contact_email",
    "contact_phone",
    "contact_address",
    "links",
    "languages",
    "specializations",
    "locale",
    "city_slug",
    "category",
    "layout",
)
#: Personal even on a company card — the history records only that they changed.
CONTACT_FIELDS = ("contact_email", "contact_phone", "contact_address")


class OrganizationProfileExists(APIException):
    status_code = 409
    default_detail = "Ta organizacja ma już swój profil."
    default_code = "organization_profile_exists"


class ProfileVersionConflict(APIException):
    status_code = 409
    default_detail = "Profil zmienił się w międzyczasie."
    default_code = "profile_version_conflict"


def _validated(profile: PublicProfile | PublicProfileTranslation) -> None:
    try:
        profile.full_clean(exclude=["organization"], validate_unique=False)
    except DjangoValidationError as error:
        raise ValidationError(error.message_dict) from error


def _validated_placement(profile: PublicProfile, organization_id: Any) -> None:
    """City and category must be dictionary values (ADR-053 §7).

    Checked on every write rather than only on publication: a draft carrying a
    city that no longer exists in the contract would fail at the one moment the
    owner least expects it.
    """
    organization = Organization.objects.filter(pk=organization_id).first()
    validate_placement(
        city_slug=profile.city_slug,
        category=profile.category,
        organization_type=organization.organization_type if organization else "",
    )


def organization_profile() -> PublicProfile:
    """The company's own profile, created on first read.

    ADR-053 §2: the business card always exists from the point of view of
    anybody who reads it, but `core.organizations` cannot create it — Core does
    not import Shared. So the panel's first read is what brings it into being,
    named after the organization and otherwise empty. Empty is not published;
    publication is a separate, deliberate act (§3).
    """
    context = authorize(PROFILES_MANAGE)
    profile = (
        _for_tenant(context.organization_id)
        .select_related("photo")
        .filter(subject_kind=ProfileSubjectKind.ORGANIZATION)
        .first()
    )
    if profile is not None:
        return profile

    organization = Organization.objects.get(pk=context.organization_id)
    with transaction.atomic():
        profile = PublicProfile(
            organization_id=context.organization_id,
            subject_kind=ProfileSubjectKind.ORGANIZATION,
            display_name=organization.name[:160],
            locale=organization.default_locale,
        )
        try:
            profile.save()
        except IntegrityError:
            # Two tabs opened the screen at once; the partial unique index made
            # one of them lose, and the winner's row is the answer.
            return _for_tenant(context.organization_id).get(
                subject_kind=ProfileSubjectKind.ORGANIZATION
            )
    record_audit(
        organization=organization,
        action=OrganizationAuditAction.PROFILE_CREATED,
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="public_profile",
        target_id=profile.id,
        metadata={"subject_kind": ProfileSubjectKind.ORGANIZATION.value, "origin": "lazy"},
    )
    return profile


def _resolve_photo(photo_id: UUID | None) -> MediaAsset | None:
    if photo_id is None:
        return None
    # `all_objects` plus an explicit organization filter rather than the tenant
    # manager: the error for somebody else's asset has to be "not found", not a
    # different shape of failure that tells them it exists.
    context = require_tenant_context()
    asset = MediaAsset.all_objects.filter(
        pk=photo_id, organization_id=context.organization_id
    ).first()
    if asset is None:
        raise ValidationError({"photo_id": "Nie ma takiego pliku w tej organizacji."})
    return asset


def _resolve_membership(membership_id: UUID | None) -> Membership | None:
    if membership_id is None:
        return None
    context = require_tenant_context()
    membership = Membership.objects.filter(
        pk=membership_id,
        organization_id=context.organization_id,
        status=MembershipStatus.ACTIVE,
    ).first()
    if membership is None:
        raise ValidationError({"membership_id": "Nie ma takiego aktywnego członka."})
    return membership


def _for_tenant(organization_id: UUID | Any) -> QuerySet[PublicProfile]:
    """Profiles of one organization, read through the plain manager.

    The tenant manager is typed against the abstract base, so a service that
    returns a concrete model cannot use it without losing the type. Naming the
    organization here says the same thing in a form both mypy and a reader
    follow; row-level security remains what enforces it.
    """
    return PublicProfile.all_objects.filter(organization_id=organization_id)


def list_profiles() -> list[PublicProfile]:
    context = authorize(ORGANIZATION_READ)
    return list(_for_tenant(context.organization_id).select_related("photo"))


def get_profile(profile_id: UUID) -> PublicProfile:
    context = authorize(ORGANIZATION_READ)
    profile = (
        _for_tenant(context.organization_id).select_related("photo").filter(pk=profile_id).first()
    )
    if profile is None:
        raise NotFound
    return profile


@transaction.atomic
def create_profile(*, subject_kind: str, **values: Any) -> PublicProfile:
    context = authorize(PROFILES_MANAGE)
    photo = _resolve_photo(values.pop("photo_id", None))
    membership = _resolve_membership(values.pop("membership_id", None))
    if subject_kind == ProfileSubjectKind.ORGANIZATION and membership is not None:
        raise ValidationError({"membership_id": "Profil organizacji nie wskazuje osoby."})

    profile = PublicProfile(
        organization_id=context.organization_id,
        subject_kind=subject_kind,
        photo=photo,
        membership=membership,
        **{field: values[field] for field in EDITABLE_FIELDS if field in values},
    )
    _validated(profile)
    _validated_placement(profile, context.organization_id)
    try:
        profile.save()
    except IntegrityError as error:
        # The partial unique index refused a second company profile.
        raise OrganizationProfileExists from error

    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=OrganizationAuditAction.PROFILE_CREATED,
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="public_profile",
        target_id=profile.id,
        metadata={"subject_kind": subject_kind},
    )
    return profile


@transaction.atomic
def update_profile(profile_id: UUID, *, expected_version: int, **values: Any) -> PublicProfile:
    context = authorize(PROFILES_MANAGE)
    profile = _for_tenant(context.organization_id).select_for_update().filter(pk=profile_id).first()
    if profile is None:
        raise NotFound
    if profile.version != expected_version:
        raise ProfileVersionConflict

    tracked = (*EDITABLE_FIELDS, "photo", "membership")
    before = audit_snapshot(profile, tracked)
    if "photo_id" in values:
        profile.photo = _resolve_photo(values.pop("photo_id"))
    if "membership_id" in values:
        membership = _resolve_membership(values.pop("membership_id"))
        if membership is not None and profile.subject_kind != ProfileSubjectKind.PERSON:
            raise ValidationError({"membership_id": "Profil organizacji nie wskazuje osoby."})
        profile.membership = membership
    for field in EDITABLE_FIELDS:
        if field in values:
            setattr(profile, field, values[field])
    profile.version += 1
    _validated(profile)
    _validated_placement(profile, context.organization_id)
    profile.save()

    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=OrganizationAuditAction.PROFILE_UPDATED,
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="public_profile",
        target_id=profile.id,
        metadata={
            "version": profile.version,
            # A person's card is personal data end to end; a company's only
            # in its contact fields.
            "changes": field_changes(
                before,
                audit_snapshot(profile, tracked),
                private=tracked
                if profile.subject_kind == ProfileSubjectKind.PERSON
                else CONTACT_FIELDS,
            ),
        },
    )
    return profile


@transaction.atomic
def delete_profile(profile_id: UUID) -> None:
    context = authorize(PROFILES_MANAGE)
    profile = _for_tenant(context.organization_id).filter(pk=profile_id).first()
    if profile is None:
        raise NotFound
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=OrganizationAuditAction.PROFILE_DELETED,
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="public_profile",
        target_id=profile.id,
        metadata={"subject_kind": profile.subject_kind},
    )
    profile.delete()


@transaction.atomic
def save_translation(profile_id: UUID, *, locale: str, **values: Any) -> PublicProfileTranslation:
    context = authorize(PROFILES_MANAGE)
    profile = _for_tenant(context.organization_id).filter(pk=profile_id).first()
    if profile is None:
        raise NotFound

    translation = PublicProfileTranslation.all_objects.filter(
        organization_id=context.organization_id, profile=profile, locale=locale
    ).first()
    if translation is None:
        translation = PublicProfileTranslation(
            organization_id=context.organization_id, profile=profile, locale=locale
        )
    else:
        translation.version += 1
    for field in ("headline", "bio", "allow_headline_fallback", "allow_bio_fallback"):
        if field in values:
            setattr(translation, field, values[field])
    _validated(translation)
    translation.save()
    return translation
