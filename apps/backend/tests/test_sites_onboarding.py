from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid7

import pytest
from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
    OrganizationStatus,
    Role,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)
from saas_core.modules.shared.sites.models import (
    Domain,
    DomainKind,
    DomainStatus,
    DomainTlsStatus,
    Publication,
    Site,
    SiteOnboardingDraft,
    SiteOnboardingMutation,
)

pytestmark = pytest.mark.django_db

PASSWORD = "Bezpieczne-Haslo-2026!"
ONBOARDING_URL = "/api/v1/sites/onboarding/"


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    cache.clear()


def onboarding_client(
    *,
    slug: str,
    role_key: str = "owner",
    sites_enabled: bool = True,
) -> tuple[APIClient, Organization, User]:
    user = User.objects.create_user(email=f"{slug}@example.test", password=PASSWORD)
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name=slug,
        slug=slug,
        status=OrganizationStatus.ACTIVE,
    )
    Membership.objects.create(
        organization=organization,
        user=user,
        role=Role.objects.get(key=role_key, organization=None),
    )
    EntitlementSnapshot.all_objects.create(
        organization=organization,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={"sites.enabled": sites_enabled},
        quotas={"sites.max": 3},
        sources={
            "sites.enabled": {"kind": "plan"},
            "sites.max": {"kind": "plan"},
        },
    )
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf/").data["csrf_token"]
    login = client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert login.status_code == 200
    return client, organization, user


def csrf(client: APIClient) -> str:
    return client.cookies["csrftoken"].value


def save_onboarding(
    client: APIClient,
    *,
    version: int,
    step: str,
    name: str,
    label: str,
    key: str,
    locale: str = "pl",
) -> Any:
    return client.put(
        ONBOARDING_URL,
        {
            "version": version,
            "step": step,
            "name": name,
            "subdomain_label": label,
            "default_locale": locale,
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf(client),
        HTTP_IDEMPOTENCY_KEY=key,
    )


def complete_onboarding(client: APIClient, *, key: str) -> Any:
    return client.post(
        f"{ONBOARDING_URL}complete/",
        {},
        format="json",
        HTTP_X_CSRFTOKEN=csrf(client),
        HTTP_IDEMPOTENCY_KEY=key,
    )


def create_site(
    client: APIClient,
    *,
    slug: str,
    label: str,
    key: str,
) -> Any:
    return client.post(
        "/api/v1/sites/",
        {
            "name": slug.replace("-", " ").title(),
            "slug": slug,
            "default_locale": "pl",
            "subdomain_label": label,
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf(client),
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_subdomain_availability_normalizes_and_hides_global_ownership() -> None:
    owner, _, _ = onboarding_client(slug="availability-owner")
    visitor, _, _ = onboarding_client(slug="availability-visitor")

    reserved = owner.get("/api/v1/sites/subdomain-availability/", {"label": "Admin"})
    invalid = owner.get("/api/v1/sites/subdomain-availability/", {"label": "---"})
    created = create_site(
        owner,
        slug="claimed-site",
        label="My Clinic",
        key="claimed-site",
    )
    taken = visitor.get(
        "/api/v1/sites/subdomain-availability/",
        {"label": "my-clinic"},
    )

    assert reserved.status_code == 200
    assert reserved.data["normalized_label"] == "admin"
    assert reserved.data["available"] is False
    assert reserved.data["reason"] == "reserved"
    assert reserved.data["suggestion"]
    assert invalid.status_code == 200
    assert invalid.data["reason"] == "invalid"
    assert created.status_code == 201
    assert taken.status_code == 200
    assert taken.data["available"] is False
    assert taken.data["reason"] == "taken"
    assert "organization" not in taken.data
    assert "site_id" not in taken.data


def test_subdomain_availability_folds_letters_ascii_cannot_decompose() -> None:
    owner, _, _ = onboarding_client(slug="availability-transliteration")

    # NFKD leaves ł intact, so stripping combining marks would delete it and
    # "Łódź" would be offered as "odz".
    polish = owner.get("/api/v1/sites/subdomain-availability/", {"label": "Łódź"})
    mixed = owner.get(
        "/api/v1/sites/subdomain-availability/",
        {"label": "Gabinet Łukasza"},
    )
    german = owner.get("/api/v1/sites/subdomain-availability/", {"label": "Straße"})

    assert polish.status_code == 200
    assert polish.data["normalized_label"] == "lodz"
    assert mixed.data["normalized_label"] == "gabinet-lukasza"
    assert german.data["normalized_label"] == "strasse"


def test_subdomain_availability_respects_release_quarantine() -> None:
    owner, _, _ = onboarding_client(slug="availability-quarantine")
    created = create_site(
        owner,
        slug="quarantine-site",
        label="quarantine-label",
        key="quarantine-site",
    )
    domain = Domain.all_objects.get(site_id=created.data["id"])
    Domain.all_objects.filter(pk=domain.pk).update(
        status=DomainStatus.RELEASED,
        tls_status=DomainTlsStatus.DISABLED,
        is_canonical=False,
        released_at=timezone.now(),
        quarantine_until=timezone.now() + timedelta(days=7),
    )

    quarantined = owner.get(
        "/api/v1/sites/subdomain-availability/",
        {"label": "quarantine-label"},
    )
    assert quarantined.status_code == 200
    assert quarantined.data["reason"] == "quarantined"
    assert quarantined.data["available"] is False


def test_subdomain_availability_is_rate_limited() -> None:
    client, _, _ = onboarding_client(slug="availability-throttle")

    responses = [
        client.get(
            "/api/v1/sites/subdomain-availability/",
            {"label": f"available-{index}"},
        )
        for index in range(31)
    ]

    assert all(response.status_code == 200 for response in responses[:30])
    assert responses[-1].status_code == 429


def test_onboarding_is_csrf_protected_resumable_audited_and_optimistic() -> None:
    client, organization, _ = onboarding_client(slug="onboarding-resume")
    foreign, _, _ = onboarding_client(slug="onboarding-foreign")

    initial = client.get(ONBOARDING_URL)
    missing_csrf = client.put(
        ONBOARDING_URL,
        {
            "version": 0,
            "step": "address",
            "name": "",
            "subdomain_label": "resume-me",
            "default_locale": "pl",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="resume-address",
    )
    saved = save_onboarding(
        client,
        version=0,
        step="address",
        name="",
        label="Resume Me",
        key="resume-address",
    )
    repeated = save_onboarding(
        client,
        version=0,
        step="address",
        name="",
        label="Resume Me",
        key="resume-address",
    )
    conflicting_key = save_onboarding(
        client,
        version=0,
        step="address",
        name="",
        label="other-label",
        key="resume-address",
    )
    stale_version = save_onboarding(
        client,
        version=0,
        step="details",
        name="My business",
        label="resume-me",
        key="resume-stale",
    )
    resumed = client.get(ONBOARDING_URL)
    foreign_state = foreign.get(ONBOARDING_URL)

    assert initial.status_code == 200
    assert initial.data["version"] == 0
    assert initial.data["step"] == "address"
    assert missing_csrf.status_code == 403
    assert saved.status_code == 200
    assert saved.data["version"] == 1
    assert saved.data["subdomain_label"] == "resume-me"
    assert saved.data["hostname"] == f"resume-me.{settings.SITES_PLATFORM_DOMAIN}"
    assert repeated.status_code == 200
    assert repeated.data == saved.data
    assert conflicting_key.status_code == 409
    assert conflicting_key.data["code"] == "sites_idempotency_conflict"
    assert stale_version.status_code == 409
    assert stale_version.data["code"] == "site_onboarding_version_conflict"
    assert resumed.data == saved.data
    assert foreign_state.status_code == 200
    assert foreign_state.data["id"] is None
    assert OrganizationAuditEntry.objects.filter(
        organization=organization,
        action="sites.onboarding.saved",
        target_id=saved.data["id"],
    ).exists()


def test_onboarding_enforces_permission_and_entitlement() -> None:
    manager, _, _ = onboarding_client(slug="onboarding-manager", role_key="manager")
    viewer, _, _ = onboarding_client(slug="onboarding-viewer", role_key="viewer")
    disabled, _, _ = onboarding_client(
        slug="onboarding-disabled",
        sites_enabled=False,
    )

    manager_save = save_onboarding(
        manager,
        version=0,
        step="address",
        name="",
        label="manager-label",
        key="manager-save",
    )
    viewer_read = viewer.get(ONBOARDING_URL)
    disabled_read = disabled.get(ONBOARDING_URL)

    assert manager_save.status_code == 403
    assert manager_save.data["code"] == "organization_permission_denied"
    assert viewer_read.status_code == 403
    assert viewer_read.data["code"] == "organization_permission_denied"
    assert disabled_read.status_code == 403
    assert disabled_read.data["code"] == "entitlement_required"


def test_onboarding_completes_idempotently_with_claimed_platform_domain() -> None:
    client, organization, _ = onboarding_client(slug="onboarding-complete")
    address = save_onboarding(
        client,
        version=0,
        step="address",
        name="",
        label="my-practice",
        key="complete-address",
    )
    details = save_onboarding(
        client,
        version=address.data["version"],
        step="details",
        name="My Practice",
        label="my-practice",
        key="complete-details",
        locale="en",
    )
    review = save_onboarding(
        client,
        version=details.data["version"],
        step="review",
        name="My Practice",
        label="my-practice",
        key="complete-review",
        locale="en",
    )

    completed = complete_onboarding(client, key="complete-site")
    repeated = complete_onboarding(client, key="complete-site")
    missing_key = client.post(
        f"{ONBOARDING_URL}complete/",
        {},
        format="json",
        HTTP_X_CSRFTOKEN=csrf(client),
    )

    assert review.data["step"] == "review"
    assert completed.status_code == 201
    assert repeated.status_code == 200
    assert repeated.data["id"] == completed.data["id"]
    assert completed.data["name"] == "My Practice"
    assert completed.data["default_locale"] == "en"
    assert missing_key.status_code == 400
    domain = Domain.all_objects.get(site_id=completed.data["id"])
    assert domain.organization == organization
    assert domain.hostname == f"my-practice.{settings.SITES_PLATFORM_DOMAIN}"
    assert domain.is_canonical is True
    draft = SiteOnboardingDraft.all_objects.get(organization=organization)
    assert draft.site_id == completed.data["id"]
    assert draft.step == "completed"


def test_subdomain_claim_race_falls_back_without_cross_tenant_takeover() -> None:
    first, _, _ = onboarding_client(slug="claim-race-first")
    second, _, _ = onboarding_client(slug="claim-race-second")
    for client, key in ((first, "first"), (second, "second")):
        saved = save_onboarding(
            client,
            version=0,
            step="review",
            name=f"{key.title()} business",
            label="shared-claim",
            key=f"{key}-review",
        )
        assert saved.status_code == 200

    first_site = complete_onboarding(first, key="first-complete")
    second_site = complete_onboarding(second, key="second-complete")
    first_domain = Domain.all_objects.get(site_id=first_site.data["id"])
    second_domain = Domain.all_objects.get(site_id=second_site.data["id"])

    assert first_site.status_code == 201
    assert second_site.status_code == 201
    assert first_domain.hostname == f"shared-claim.{settings.SITES_PLATFORM_DOMAIN}"
    assert second_domain.hostname != first_domain.hostname
    assert second_domain.hostname.startswith("shared-claim-")
    assert second_domain.hostname.endswith(f".{settings.SITES_PLATFORM_DOMAIN}")


@override_settings(PUBLIC_SITE_SCHEME="https")
def test_platform_domain_change_is_audited_and_old_hostname_redirects() -> None:
    client, organization, user = onboarding_client(slug="platform-change")
    created = create_site(
        client,
        slug="old-site",
        label="old-address",
        key="old-site",
    )
    site = Site.all_objects.get(pk=created.data["id"])
    old_domain = Domain.all_objects.get(site=site, kind=DomainKind.PLATFORM)
    publication = Publication.all_objects.create(
        organization=organization,
        site=site,
        sequence=1,
        snapshot={
            "site_id": str(site.id),
            "site_slug": site.slug,
            "default_locale": "pl",
            "design_tokens": {},
            "pages": [
                {
                    "page_id": str(uuid7()),
                    "key": "home",
                    "version_id": str(uuid7()),
                    "version": 1,
                    "blocks": [],
                    "media_asset_ids": [],
                    "locales": [
                        {
                            "locale": "pl",
                            "path": "/",
                            "canonical_path": "/",
                            "title": "Start",
                            "description": "",
                            "social_title": "",
                            "social_description": "",
                        }
                    ],
                    "hreflang": {"pl": "/"},
                    "x_default": "/",
                }
            ],
        },
        snapshot_hash="a" * 64,
        created_by=user,
        idempotency_key="platform-change-publication",
    )
    Site.all_objects.filter(pk=site.pk).update(current_publication=publication)

    changed = client.put(
        f"/api/v1/sites/{site.id}/platform-domain/",
        {"label": "new-address"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf(client),
        HTTP_IDEMPOTENCY_KEY="platform-change",
    )
    repeated = client.put(
        f"/api/v1/sites/{site.id}/platform-domain/",
        {"label": "new-address"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf(client),
        HTTP_IDEMPOTENCY_KEY="platform-change",
    )
    alias = APIClient().get(
        "/api/v1/public/site/",
        {"path": "/"},
        HTTP_HOST=old_domain.hostname,
    )

    assert changed.status_code == 201
    assert repeated.status_code == 200
    assert repeated.data["id"] == changed.data["id"]
    assert changed.data["hostname"] == f"new-address.{settings.SITES_PLATFORM_DOMAIN}"
    assert alias.status_code == 308
    assert alias["Location"] == f"https://{changed.data['hostname']}/"
    assert OrganizationAuditEntry.objects.filter(
        organization=organization,
        action="sites.domain.platform_changed",
        target_id=changed.data["id"],
    ).exists()


def test_database_guards_onboarding_tenant_links_and_append_only_mutations() -> None:
    first, first_org, first_user = onboarding_client(slug="guard-first")
    _, second_org, second_user = onboarding_client(slug="guard-second")
    site_response = create_site(
        first,
        slug="guard-site",
        label="guard-site",
        key="guard-site",
    )
    site = Site.all_objects.get(pk=site_response.data["id"])

    with pytest.raises(DatabaseError), transaction.atomic():
        SiteOnboardingDraft.all_objects.create(
            organization=second_org,
            site=site,
            step="completed",
            created_by=second_user,
            updated_by=second_user,
        )

    draft = SiteOnboardingDraft.all_objects.create(
        organization=second_org,
        step="address",
        created_by=second_user,
        updated_by=second_user,
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        SiteOnboardingMutation.all_objects.create(
            organization=first_org,
            draft=draft,
            actor=first_user,
            idempotency_key="cross-tenant",
            request_hash="a" * 64,
            resulting_version=1,
        )

    mutation = SiteOnboardingMutation.all_objects.create(
        organization=second_org,
        draft=draft,
        actor=second_user,
        idempotency_key="append-only",
        request_hash="b" * 64,
        resulting_version=1,
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        SiteOnboardingMutation.all_objects.filter(pk=mutation.pk).update(
            resulting_version=2
        )
