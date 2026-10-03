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
from rest_framework.exceptions import APIException, ErrorDetail, NotFound, ValidationError

from saas_core.content_protocol.provenance import ORIGIN_HUMAN, Provenance, unit_hash
from saas_core.content_protocol.units import UNIT_TEXT
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import (
    audit_snapshot,
    field_changes,
    record_audit,
)
from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.locales import (
    assert_organization_content_locale,
    organization_content_locales,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    MembershipStatus,
    Organization,
    OrganizationAuditAction,
)
from saas_core.modules.core.organizations.permissions import ORGANIZATION_READ
from saas_core.modules.shared.media.models import MediaAsset

from .catalog import (
    ProfileNotPublishable,
    catalog_entry_for,
    publishable,
    refresh_catalog_entry,
    validate_placement,
)
from .models import ProfileSubjectKind, PublicProfile, PublicProfileTranslation
from .permissions import PROFILES_MANAGE
from .translation_source import (
    LEGACY_SOURCE,
    LINK_PREFIX,
    apply_translation,
    notify_card_changed,
    source_units,
)

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
    # A profile speaks one of the company's languages (ADR-071 pkt 3 and 22).
    assert_organization_content_locale(profile.locale, organization_id=profile.organization_id)


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
        profile = _new_organization_profile(organization)
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


def _new_organization_profile(organization: Organization) -> PublicProfile:
    """The card a company starts with: its name, otherwise empty, unsaved."""
    return PublicProfile(
        organization_id=organization.id,
        subject_kind=ProfileSubjectKind.ORGANIZATION,
        display_name=organization.name[:160],
        # The customers' language, not the panel's (ADR-071 pkt 4).
        locale=(organization_content_locales(organization) or (organization.default_locale,))[0],
    )


def existing_organization_profile() -> tuple[PublicProfile | None, bool]:
    """The company's card if it exists, and whether it is in the catalogue —
    read without bringing the card into being, unlike `organization_profile`."""
    context = authorize(PROFILES_MANAGE)
    profile = (
        _for_tenant(context.organization_id)
        .filter(subject_kind=ProfileSubjectKind.ORGANIZATION)
        .first()
    )
    return profile, catalog_entry_for(context.organization_id) is not None


def planned_organization_profile(
    *, changes: dict[str, Any]
) -> tuple[PublicProfile, int, dict[str, tuple[Any, Any]], bool]:
    """The company's card as `changes` would leave it, nothing written — not
    even the card, when the company has none yet (its version is then 0).

    Checked by the rules of `update_profile`, including the catalogue's: a card
    in the catalogue cannot lose its name, city or category.
    """
    context = authorize(PROFILES_MANAGE)
    existing, in_catalog = existing_organization_profile()
    profile = existing or _new_organization_profile(
        Organization.objects.get(pk=context.organization_id)
    )
    before = {field: getattr(profile, field) for field in changes}
    for field, value in changes.items():
        setattr(profile, field, value)
    _validated(profile)
    _validated_placement(profile, context.organization_id)
    if in_catalog and not publishable(profile):
        raise ProfileNotPublishable(
            "Wizytówka jest w katalogu: nazwa, miasto i kategoria muszą zostać uzupełnione."
        )
    diffs = {
        field: (before[field], getattr(profile, field))
        for field in sorted(changes)
        if getattr(profile, field) != before[field]
    }
    return profile, existing.version if existing is not None else 0, diffs, in_catalog


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
    texts_before = [unit.source_hash for unit in source_units(profile)]
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
    refresh_catalog_entry(profile)
    if [unit.source_hash for unit in source_units(profile)] != texts_before:
        notify_card_changed(context=context, profile_id=profile.id)

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
    notify_card_changed(context=context, profile_id=profile.id, change="deleted")
    profile.delete()


def list_translations(
    profile_id: UUID,
) -> tuple[PublicProfile, list[tuple[str, PublicProfileTranslation | None]]]:
    """The card and each other language of the company, with its row or none."""
    profile = get_profile(profile_id)
    organization = Organization.objects.get(pk=profile.organization_id)
    rows = {
        row.locale: row
        for row in PublicProfileTranslation.all_objects.filter(
            organization_id=profile.organization_id, profile=profile
        )
    }
    locales = [
        code for code in organization_content_locales(organization) if code != profile.locale
    ]
    locales += sorted(code for code in rows if code not in locales and code != profile.locale)
    return profile, [(code, rows.get(code)) for code in locales]


@transaction.atomic
def save_translation(
    profile_id: UUID, *, locale: str, expected_version: int, **values: Any
) -> PublicProfileTranslation:
    """A person's text of the card in another language, at the version they
    saw (0 for a language the card does not have yet)."""
    context = authorize(PROFILES_MANAGE)
    profile = _for_tenant(context.organization_id).select_for_update().filter(pk=profile_id).first()
    if profile is None:
        raise NotFound
    if locale == profile.locale:
        raise ValidationError({
            "locale": [ErrorDetail("To język, w którym karta jest napisana.", "locale_is_source")]
        })
    assert_organization_content_locale(locale, organization_id=context.organization_id)
    current = PublicProfileTranslation.all_objects.filter(
        organization_id=context.organization_id, profile=profile, locale=locale
    ).first()
    if (current.version if current is not None else 0) != expected_version:
        raise ProfileVersionConflict
    units = {unit.key: unit for unit in source_units(profile)}
    texts: dict[str, tuple[str, Provenance]] = {}
    wanted = {field: values[field] for field in ("headline", "bio") if field in values}
    labels = values.get("link_labels") or {}
    unknown = [key for key in labels if key not in units or not key.startswith(LINK_PREFIX)]
    if unknown:
        raise ValidationError({
            f"link_labels.{key}": [ErrorDetail("Karta nie ma takiego linku.", "unknown_link")]
            for key in unknown
        })
    wanted.update(labels)
    for key, text in wanted.items():
        unit = units.get(key)
        texts[key] = (
            text,
            Provenance(
                origin=ORIGIN_HUMAN,
                source_hash=unit.source_hash if unit is not None else LEGACY_SOURCE,
                written_hash=unit_hash(UNIT_TEXT, text) if text else "",
            ),
        )
    flags = {
        flag: values[flag]
        for flag in ("allow_headline_fallback", "allow_bio_fallback")
        if flag in values
    }
    try:
        translation, _replaced = apply_translation(
            profile, locale, texts, actor_id=context.actor_id, flags=flags
        )
    except DjangoValidationError as error:
        raise ValidationError(error.message_dict) from error
    return translation
