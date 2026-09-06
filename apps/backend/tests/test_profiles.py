"""Public profiles: who a company and its people are, as data (ADR-036).

The rules worth a test are the ones a later change could quietly undo: a company
has exactly one profile, a person profile may name a member and a company one
may not, the photo has to belong to the same tenant, editing is version-locked,
and nothing here is writable without the permission.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid7

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationStatus,
    Role,
)
from saas_core.modules.core.organizations.permissions import SYSTEM_ROLE_PERMISSIONS
from saas_core.modules.shared.media.models import MediaAsset, MediaAssetState
from saas_core.modules.shared.profiles.models import ProfileSubjectKind, PublicProfile
from saas_core.modules.shared.profiles.services import (
    OrganizationProfileExists,
    ProfileVersionConflict,
    create_profile,
    delete_profile,
    list_profiles,
    save_translation,
    update_profile,
)

pytestmark = pytest.mark.django_db


def _organization(slug: str) -> Organization:
    organization = Organization(
        name=slug.title(), slug=slug, status=OrganizationStatus.ACTIVE
    )
    set_local_organization_id(organization.id)
    organization.save()
    return organization


def _context(organization: Organization, *, role: str = "owner") -> TenantContext:
    return TenantContext(
        organization_id=organization.id,
        membership_id=uuid7(),
        actor_id=uuid7(),
        role_key=role,
        permissions=frozenset(SYSTEM_ROLE_PERMISSIONS[role]),
    )


def _asset(organization: Organization) -> MediaAsset:
    identifier = uuid7()
    return MediaAsset.all_objects.create(
        organization=organization,
        original_filename="zdjecie.png",
        declared_mime="image/png",
        expected_size=64,
        object_key=f"{organization.id}/{identifier}.png",
        quota_reservation_key=f"test-{identifier}",
        state=MediaAssetState.READY,
        upload_expires_at=timezone.now() + timedelta(hours=1),
        created_by=_user(),
        idempotency_key=f"test-{identifier}",
        request_hash=f"{identifier}".replace("-", ""),
    )


def _user() -> Any:
    return get_user_model().objects.create_user(
        email=f"osoba-{uuid7()}@example.test", password="Profiles-2026!"
    )


def _member(organization: Organization) -> Membership:
    user = _user()
    return Membership.objects.create(
        organization=organization,
        user=user,
        role=Role.objects.get(key="admin", organization=None),
    )


def _create(organization: Organization, **values: Any) -> PublicProfile:
    with activate_tenant_context(_context(organization)):
        set_local_organization_id(organization.id)
        return create_profile(**values)


def test_a_company_has_exactly_one_profile() -> None:
    organization = _organization("profil-jeden")
    _create(
        organization,
        subject_kind=ProfileSubjectKind.ORGANIZATION,
        display_name="Gabinet Kowalski",
    )

    with pytest.raises(OrganizationProfileExists):
        _create(
            organization,
            subject_kind=ProfileSubjectKind.ORGANIZATION,
            display_name="Drugi profil firmy",
        )


def test_a_company_profile_may_not_name_a_person() -> None:
    organization = _organization("profil-osoba")
    membership = _member(organization)

    with pytest.raises(ValidationError):
        _create(
            organization,
            subject_kind=ProfileSubjectKind.ORGANIZATION,
            display_name="Gabinet",
            membership_id=membership.id,
        )


def test_a_person_profile_works_without_an_account() -> None:
    """A visiting specialist has no panel login and still appears on the site."""
    organization = _organization("profil-bez-konta")

    profile = _create(
        organization,
        subject_kind=ProfileSubjectKind.PERSON,
        display_name="dr Anna Nowak",
        headline="Stomatolog",
        languages=["pl", "en"],
        specializations=["stomatologia.zachowawcza"],
    )

    assert profile.membership_id is None
    assert profile.languages == ["pl", "en"]


def test_a_photo_from_another_tenant_is_not_found() -> None:
    organization = _organization("profil-moj")
    stranger = _organization("profil-obcy")
    foreign_asset = _asset(stranger)

    with pytest.raises(ValidationError):
        _create(
            organization,
            subject_kind=ProfileSubjectKind.PERSON,
            display_name="dr Jan Kowalski",
            photo_id=foreign_asset.id,
        )


def test_markup_in_a_public_field_is_refused() -> None:
    """The bio is rendered on a public page; a field accepting HTML is stored XSS."""
    organization = _organization("profil-html")

    with pytest.raises(ValidationError):
        _create(
            organization,
            subject_kind=ProfileSubjectKind.PERSON,
            display_name="dr Ewa Lis",
            bio="<script>alert(1)</script>",
        )


def test_editing_is_version_locked() -> None:
    organization = _organization("profil-wersja")
    profile = _create(
        organization,
        subject_kind=ProfileSubjectKind.PERSON,
        display_name="dr Anna Nowak",
    )

    with activate_tenant_context(_context(organization)):
        set_local_organization_id(organization.id)
        updated = update_profile(
            profile.id, expected_version=profile.version, headline="Ortodonta"
        )
        assert updated.version == profile.version + 1

        with pytest.raises(ProfileVersionConflict):
            update_profile(profile.id, expected_version=profile.version, headline="Inny")


def test_a_translation_is_one_row_per_locale() -> None:
    organization = _organization("profil-tlumaczenie")
    profile = _create(
        organization,
        subject_kind=ProfileSubjectKind.PERSON,
        display_name="dr Anna Nowak",
        headline="Stomatolog",
    )

    with activate_tenant_context(_context(organization)):
        set_local_organization_id(organization.id)
        first = save_translation(profile.id, locale="en", headline="Dentist")
        second = save_translation(profile.id, locale="en", headline="Dental surgeon")

    assert first.id == second.id
    assert second.headline == "Dental surgeon"
    assert second.version == first.version + 1


def test_a_role_without_the_permission_may_read_but_not_write() -> None:
    organization = _organization("profil-uprawnienia")
    profile = _create(
        organization,
        subject_kind=ProfileSubjectKind.PERSON,
        display_name="dr Anna Nowak",
    )

    with activate_tenant_context(_context(organization, role="staff")):
        set_local_organization_id(organization.id)
        assert [row.id for row in list_profiles()] == [profile.id]
        with pytest.raises(PermissionDenied):
            update_profile(profile.id, expected_version=profile.version, headline="X")
        with pytest.raises(PermissionDenied):
            delete_profile(profile.id)


def test_another_tenants_profile_is_not_found() -> None:
    organization = _organization("profil-a")
    stranger = _organization("profil-b")
    theirs = _create(
        stranger,
        subject_kind=ProfileSubjectKind.PERSON,
        display_name="dr Obcy",
    )

    with activate_tenant_context(_context(organization)):
        set_local_organization_id(organization.id)
        assert list_profiles() == []
        with pytest.raises(NotFound):
            update_profile(theirs.id, expected_version=theirs.version, headline="X")
