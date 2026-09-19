from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid7

import dns.exception
import dns.resolver
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
from saas_core.modules.shared.sites.dns_verification import (
    check_domain_dns,
    verify_domain_dns,
)
from saas_core.modules.shared.sites.domains import InvalidHostname, normalize_hostname
from saas_core.modules.shared.sites.models import (
    Domain,
    DomainKind,
    DomainStatus,
    DomainTlsStatus,
    Publication,
    Site,
)

pytestmark = pytest.mark.django_db

PASSWORD = "Bezpieczne-Haslo-2026!"


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    cache.clear()


class FakeResolver:
    def __init__(
        self,
        records: dict[tuple[str, str], set[str]] | None = None,
        errors: dict[tuple[str, str], Exception] | None = None,
    ) -> None:
        self.records = records or {}
        self.errors = errors or {}

    def resolve_values(self, name: str, record_type: str) -> set[str]:
        key = (name, record_type)
        if key in self.errors:
            raise self.errors[key]
        if key not in self.records:
            raise dns.resolver.NoAnswer
        return self.records[key]


def domain_client(
    *,
    slug: str,
    role_key: str = "owner",
    sites_enabled: bool = True,
    custom_domain_enabled: bool = True,
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
        role=Role.objects.get(key=role_key, organization=None, organization_type=""),
    )
    EntitlementSnapshot.all_objects.create(
        organization=organization,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={
            "sites.enabled": sites_enabled,
            "custom_domain.enabled": custom_domain_enabled,
        },
        quotas={"sites.max": 3},
        sources={
            "sites.enabled": {"kind": "plan"},
            "custom_domain.enabled": {"kind": "plan"},
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


def create_site(client: APIClient, slug: str, *, key: str | None = None) -> Any:
    return client.post(
        "/api/v1/sites/",
        {"name": slug, "slug": slug, "default_locale": "pl"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf(client),
        HTTP_IDEMPOTENCY_KEY=key or f"site-{slug}",
    )


def create_custom_domain(
    client: APIClient,
    site_id: str,
    hostname: str,
    *,
    key: str,
) -> Any:
    return client.post(
        f"/api/v1/sites/{site_id}/domains/",
        {"hostname": hostname},
        format="json",
        HTTP_X_CSRFTOKEN=csrf(client),
        HTTP_IDEMPOTENCY_KEY=key,
    )


def domain_action(client: APIClient, domain_id: str, action: str, *, key: str) -> Any:
    return client.post(
        f"/api/v1/sites/domains/{domain_id}/actions/",
        {"action": action},
        format="json",
        HTTP_X_CSRFTOKEN=csrf(client),
        HTTP_IDEMPOTENCY_KEY=key,
    )


def publish_fixture(
    site: Site, user: User, *, trailing_slash: bool = False
) -> Publication:
    tail = "/" if trailing_slash else ""
    snapshot = {
        "site_id": str(site.id),
        "site_slug": site.slug,
        "default_locale": "pl",
        "design_tokens": {
            "schemaVersion": 1,
            "palette": "neutral",
            "typography": "sans",
            "radius": "medium",
            "spacing": "comfortable",
        },
        "pages": [
            {
                "page_id": str(uuid7()),
                "key": "offer",
                "version_id": str(uuid7()),
                "version": 1,
                "blocks": [
                    {
                        "block_type": "core.hero",
                        "schema_version": 1,
                        "data": {"heading": "Oferta"},
                    }
                ],
                "media_asset_ids": [],
                "locales": [
                    {
                        "locale": "pl",
                        "path": f"/oferta{tail}",
                        "canonical_path": f"/oferta{tail}",
                        "title": "Oferta",
                        "description": "Opis oferty",
                        "social_title": "Oferta social",
                        "social_description": "Opis social",
                    },
                    {
                        "locale": "en",
                        "path": f"/en/offer{tail}",
                        "canonical_path": f"/en/offer{tail}",
                        "title": "Offer",
                        "description": "Offer description",
                        "social_title": "Offer social",
                        "social_description": "Social description",
                    },
                ],
                "hreflang": {"pl": f"/oferta{tail}", "en": f"/en/offer{tail}"},
                "x_default": f"/oferta{tail}",
            }
        ],
    }
    publication = Publication.all_objects.create(
        organization=site.organization,
        site=site,
        sequence=1,
        snapshot=snapshot,
        snapshot_hash="",
        created_by=user,
        idempotency_key="published-fixture",
    )
    Site.all_objects.filter(pk=site.pk).update(current_publication=publication)
    from saas_core.modules.shared.sites.tls import invalidate_site_tls_decisions

    invalidate_site_tls_decisions(site_id=site.id)
    site.refresh_from_db()
    return publication


def test_hostname_normalization_covers_port_case_unicode_and_injection() -> None:
    assert normalize_hostname("EXAMPLE.COM.:8443", allow_port=True) == "example.com"
    assert normalize_hostname("Zażółć.PL") == "xn--za-6ja4f8n1l.pl"

    for value in (
        "example.com/path",
        "example.com@evil.test",
        "example.com:invalid",
        "127.0.0.1",
        "*.example.com",
        " example.com",
        "example..com",
    ):
        with pytest.raises(InvalidHostname):
            normalize_hostname(value, allow_port=True)


def test_site_creation_reserves_verified_canonical_platform_subdomain() -> None:
    client, organization, _ = domain_client(slug="domain-platform")

    response = create_site(client, "clinic")

    assert response.status_code == 201
    domain = Domain.all_objects.get(site_id=response.data["id"])
    assert domain.organization == organization
    assert domain.hostname.startswith("clinic-")
    assert domain.hostname.endswith(f".{settings.SITES_PLATFORM_DOMAIN}")
    assert domain.kind == DomainKind.PLATFORM
    assert domain.status == DomainStatus.VERIFIED
    assert domain.tls_status == DomainTlsStatus.ELIGIBLE
    assert domain.is_canonical is True


def test_custom_domain_is_csrf_protected_idempotent_entitled_and_tenant_scoped() -> None:
    client, organization, _ = domain_client(slug="domain-owner")
    foreign, _, _ = domain_client(slug="domain-foreign")
    starter, _, _ = domain_client(
        slug="domain-starter",
        custom_domain_enabled=False,
    )
    viewer, _, _ = domain_client(slug="domain-viewer", role_key="viewer")
    site = create_site(client, "owner-site")
    starter_site = create_site(starter, "starter-site")
    payload_url = f"/api/v1/sites/{site.data['id']}/domains/"

    missing_csrf = client.post(
        payload_url,
        {"hostname": "www.example.test"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="custom-domain",
    )
    created = create_custom_domain(
        client,
        site.data["id"],
        "WWW.Example.Test.",
        key="custom-domain",
    )
    repeated = create_custom_domain(
        client,
        site.data["id"],
        "WWW.Example.Test.",
        key="custom-domain",
    )
    conflicting_key = create_custom_domain(
        client,
        site.data["id"],
        "other.example.test",
        key="custom-domain",
    )
    foreign_attempt = create_custom_domain(
        foreign,
        site.data["id"],
        "foreign.example.test",
        key="foreign-domain",
    )
    no_entitlement = create_custom_domain(
        starter,
        starter_site.data["id"],
        "starter.example.test",
        key="starter-domain",
    )
    no_permission = create_custom_domain(
        viewer,
        site.data["id"],
        "viewer.example.test",
        key="viewer-domain",
    )

    assert missing_csrf.status_code == 403
    assert created.status_code == 201
    assert repeated.status_code == 200
    assert created.data["id"] == repeated.data["id"]
    assert created.data["hostname"] == "www.example.test"
    assert created.data["verification_name"] == "_saas-core.www.example.test"
    assert created.data["verification_token"].startswith(
        f"saas-core-domain-verification={created.data['id']}."
    )
    assert conflicting_key.status_code == 409
    assert foreign_attempt.status_code == 404
    assert no_entitlement.status_code == 403
    assert no_entitlement.data["code"] == "entitlement_required"
    assert no_permission.status_code == 403
    assert no_permission.data["code"] == "organization_permission_denied"
    assert OrganizationAuditEntry.objects.filter(
        organization=organization,
        action="sites.domain.created",
        target_id=created.data["id"],
    ).exists()


def test_global_hostname_ownership_and_release_quarantine_prevent_takeover() -> None:
    owner, _, _ = domain_client(slug="domain-takeover-owner")
    attacker, _, _ = domain_client(slug="domain-takeover-attacker")
    owner_site = create_site(owner, "takeover-owner")
    attacker_site = create_site(attacker, "takeover-attacker")
    created = create_custom_domain(
        owner,
        owner_site.data["id"],
        "claimed.example.test",
        key="claim-owner",
    )

    active_takeover = create_custom_domain(
        attacker,
        attacker_site.data["id"],
        "claimed.example.test",
        key="claim-attacker-active",
    )
    released = domain_action(
        owner,
        created.data["id"],
        "release",
        key="release-owner",
    )
    quarantined_takeover = create_custom_domain(
        attacker,
        attacker_site.data["id"],
        "claimed.example.test",
        key="claim-attacker-quarantine",
    )

    assert active_takeover.status_code == 409
    assert active_takeover.data["code"] == "domain_hostname_conflict"
    assert released.status_code == 200
    assert released.data["status"] == DomainStatus.RELEASED
    assert quarantined_takeover.status_code == 409
    assert quarantined_takeover.data["code"] == "domain_quarantined"

    Domain.all_objects.filter(pk=created.data["id"]).update(
        quarantine_until=timezone.now() - timedelta(seconds=1)
    )
    after_quarantine = create_custom_domain(
        attacker,
        attacker_site.data["id"],
        "claimed.example.test",
        key="claim-attacker-after",
    )
    assert after_quarantine.status_code == 201
    assert after_quarantine.data["verification_token"] != created.data["verification_token"]


def test_canonical_domain_can_roll_back_to_platform_before_dns_release() -> None:
    client, _, _ = domain_client(slug="domain-canonical-rollback")
    site_response = create_site(client, "canonical-rollback")
    platform = Domain.all_objects.get(
        site_id=site_response.data["id"],
        kind=DomainKind.PLATFORM,
    )
    custom_response = create_custom_domain(
        client,
        site_response.data["id"],
        "canonical.example.test",
        key="canonical-custom",
    )
    Domain.all_objects.filter(pk=custom_response.data["id"]).update(
        status=DomainStatus.VERIFIED,
        tls_status=DomainTlsStatus.ELIGIBLE,
    )
    canonical = domain_action(
        client,
        custom_response.data["id"],
        "set_canonical",
        key="canonical-set",
    )
    platform.refresh_from_db()
    platform_was_canonical = platform.is_canonical

    disabled = domain_action(
        client,
        custom_response.data["id"],
        "disable",
        key="canonical-disable",
    )
    platform.refresh_from_db()

    assert canonical.status_code == 200
    assert canonical.data["is_canonical"] is True
    assert platform_was_canonical is False
    assert disabled.status_code == 200
    assert disabled.data["is_canonical"] is False
    assert platform.is_canonical is True


@override_settings(
    DOMAIN_DNS_CNAME_TARGET="sites.platform.test",
    DOMAIN_DNS_EXPECTED_IPV4=("203.0.113.10",),
    DOMAIN_DNS_EXPECTED_IPV6=("2001:db8::10",),
)
def test_dns_requires_exact_per_domain_txt_and_valid_routing() -> None:
    token = "saas-core-domain-verification=domain.token"
    name = "_saas-core.www.example.test"
    valid = FakeResolver({
        (name, "TXT"): {token},
        ("www.example.test", "CNAME"): {"sites.platform.test"},
    })
    copied = FakeResolver({
        (name, "TXT"): {"saas-core-domain-verification=other.token"},
        ("www.example.test", "CNAME"): {"sites.platform.test"},
    })
    bad_route = FakeResolver({
        (name, "TXT"): {token},
        ("www.example.test", "A"): {"198.51.100.99"},
    })

    assert check_domain_dns(
        hostname="www.example.test",
        verification_name=name,
        verification_token=token,
        resolver=valid,
    ).verified
    copied_result = check_domain_dns(
        hostname="www.example.test",
        verification_name=name,
        verification_token=token,
        resolver=copied,
    )
    route_result = check_domain_dns(
        hostname="www.example.test",
        verification_name=name,
        verification_token=token,
        resolver=bad_route,
    )
    assert copied_result.code == "txt_mismatch"
    assert route_result.code == "routing_mismatch"


@override_settings(
    DOMAIN_DNS_CNAME_TARGET="sites.platform.test",
    DOMAIN_REVERIFY_SECONDS=3600,
    DOMAIN_TRANSIENT_GRACE_SECONDS=86400,
)
def test_dns_timeout_preserves_recent_verification_but_nxdomain_revokes_it() -> None:
    client, _, _ = domain_client(slug="domain-dns-state")
    site = create_site(client, "dns-state")
    created = create_custom_domain(
        client,
        site.data["id"],
        "dns-state.example.test",
        key="dns-state-domain",
    )
    domain = Domain.all_objects.get(pk=created.data["id"])
    records = {
        (domain.verification_name, "TXT"): {domain.verification_token},
        (domain.hostname, "CNAME"): {"sites.platform.test"},
    }
    verified_at = timezone.now()
    verified = verify_domain_dns(
        domain_id=domain.id,
        resolver=FakeResolver(records),
        checked_at=verified_at,
    )
    timeout = verify_domain_dns(
        domain_id=domain.id,
        resolver=FakeResolver(
            errors={(domain.verification_name, "TXT"): dns.exception.Timeout()}
        ),
        checked_at=verified_at + timedelta(minutes=5),
    )
    domain.refresh_from_db()

    assert verified is not None and verified.verified
    assert timeout is not None and timeout.transient
    assert domain.status == DomainStatus.VERIFIED
    assert domain.tls_status == DomainTlsStatus.ELIGIBLE
    assert domain.dns_error_code == "resolver_unavailable"

    nxdomain = verify_domain_dns(
        domain_id=domain.id,
        resolver=FakeResolver(
            errors={(domain.verification_name, "TXT"): dns.resolver.NXDOMAIN()}
        ),
        checked_at=verified_at + timedelta(minutes=10),
    )
    domain.refresh_from_db()
    assert nxdomain is not None and nxdomain.code == "nxdomain"
    assert domain.status == DomainStatus.FAILED
    assert domain.tls_status == DomainTlsStatus.FAILED


def test_tls_authorization_denies_arbitrary_pending_and_inactive_domains() -> None:
    client, organization, user = domain_client(slug="domain-tls")
    site_response = create_site(client, "tls-site")
    site = Site.all_objects.get(pk=site_response.data["id"])
    platform = Domain.all_objects.get(site=site, kind=DomainKind.PLATFORM)

    before_publication = APIClient().get(
        "/internal/caddy/domains/authorize/",
        {"domain": platform.hostname},
    )
    arbitrary = APIClient().get(
        "/internal/caddy/domains/authorize/",
        {"domain": "arbitrary.example.test"},
    )
    publish_fixture(site, user)
    allowed = APIClient().get(
        "/internal/caddy/domains/authorize/",
        {"domain": platform.hostname.upper() + "."},
    )
    organization.status = OrganizationStatus.SUSPENDED
    organization.save(update_fields=["status", "updated_at"])
    cache.clear()
    suspended = APIClient().get(
        "/internal/caddy/domains/authorize/",
        {"domain": platform.hostname},
    )

    assert before_publication.status_code == 404
    assert arbitrary.status_code == 404
    assert allowed.status_code == 204
    assert suspended.status_code == 404


@override_settings(PUBLIC_SITE_SCHEME="https")
def test_public_renderer_matches_paths_however_they_end() -> None:
    """Publishing writes trailing-slash paths ("/oferta/"), and the resolver
    trimmed only the request before comparing — so every page but the home page
    answered 404 in production while this suite, whose fixture omits the slash,
    stayed green."""
    client, _, user = domain_client(slug="domain-slash")
    site_response = create_site(client, "slash-site")
    site = Site.all_objects.get(pk=site_response.data["id"])
    publish_fixture(site, user, trailing_slash=True)
    platform = Domain.all_objects.get(site=site, kind=DomainKind.PLATFORM)

    with_slash = APIClient().get(
        "/api/v1/public/site/",
        {"path": "/oferta/"},
        HTTP_HOST=platform.hostname,
    )
    without_slash = APIClient().get(
        "/api/v1/public/site/",
        {"path": "/oferta"},
        HTTP_HOST=platform.hostname,
    )

    assert with_slash.status_code == 200
    assert with_slash.data["locale"] == "pl"
    # The canonical form differing only by a trailing slash must not send the
    # visitor back to the address they already requested.
    assert without_slash.status_code == 200


@override_settings(PUBLIC_SITE_SCHEME="https")
def test_public_renderer_resolves_only_host_publication_locale_and_canonical() -> None:
    client, _, user = domain_client(slug="domain-public")
    site_response = create_site(client, "public-site")
    site = Site.all_objects.get(pk=site_response.data["id"])
    publication = publish_fixture(site, user)
    platform = Domain.all_objects.get(site=site, kind=DomainKind.PLATFORM)
    custom_response = create_custom_domain(
        client,
        site_response.data["id"],
        "www.public.example.test",
        key="public-custom",
    )
    Domain.all_objects.filter(pk=custom_response.data["id"]).update(
        status=DomainStatus.VERIFIED,
        tls_status=DomainTlsStatus.ELIGIBLE,
    )

    polish = APIClient().get(
        "/api/v1/public/site/",
        {"path": "/oferta"},
        HTTP_HOST=platform.hostname.upper() + ".:443",
    )
    english = APIClient().get(
        "/api/v1/public/site/",
        {"path": "/en/offer"},
        HTTP_HOST=platform.hostname,
    )
    alias = APIClient().get(
        "/api/v1/public/site/",
        {"path": "/oferta"},
        HTTP_HOST="www.public.example.test",
    )
    root = APIClient().get(
        "/api/v1/public/site/",
        {"path": "/"},
        HTTP_HOST=platform.hostname,
    )
    unknown = APIClient().get(
        "/api/v1/public/site/",
        {"path": "/oferta"},
        HTTP_HOST="unknown.example.test",
    )
    injected = APIClient().get(
        "/api/v1/public/site/",
        {"path": "/oferta"},
        HTTP_HOST=f"{platform.hostname}@evil.test",
    )

    assert polish.status_code == 200
    assert polish.data["publication_id"] == str(publication.id)
    assert polish.data["locale"] == "pl"
    assert polish.data["canonical_url"] == f"https://{platform.hostname}/oferta"
    assert polish.data["hreflang"]["en"] == f"https://{platform.hostname}/en/offer"
    assert "organization_id" not in polish.data
    assert english.status_code == 200
    assert english.data["locale"] == "en"
    assert alias.status_code == 308
    assert alias["Location"] == f"https://{platform.hostname}/oferta"
    assert root.status_code == 200
    assert root.data["title"] == "Oferta"
    assert root.data["canonical_url"] == f"https://{platform.hostname}/oferta"
    assert unknown.status_code == 404
    assert injected.status_code == 400


def test_database_rejects_two_active_domains_with_same_hostname() -> None:
    first_client, first_org, first_user = domain_client(slug="domain-db-first")
    second_client, second_org, second_user = domain_client(slug="domain-db-second")
    first_site = Site.all_objects.get(pk=create_site(first_client, "db-first").data["id"])
    second_site = Site.all_objects.get(pk=create_site(second_client, "db-second").data["id"])
    Domain.all_objects.create(
        organization=first_org,
        site=first_site,
        hostname="db-claimed.example.test",
        kind=DomainKind.CUSTOM,
        verification_name="_saas-core.db-claimed.example.test",
        verification_token="first",
        created_by=first_user,
        idempotency_key="db-first-domain",
        request_hash="1" * 64,
    )

    with pytest.raises(DatabaseError), transaction.atomic():
        Domain.all_objects.create(
            organization=second_org,
            site=second_site,
            hostname="db-claimed.example.test",
            kind=DomainKind.CUSTOM,
            verification_name="_saas-core.db-claimed.example.test",
            verification_token="second",
            created_by=second_user,
            idempotency_key="db-second-domain",
            request_hash="2" * 64,
        )
