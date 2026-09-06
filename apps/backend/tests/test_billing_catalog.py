from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.context import (
    MissingTenantContext,
    TenantContext,
    activate_tenant_context,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementGrant,
    EntitlementSnapshot,
    Feature,
    GrantSource,
    Plan,
    PlanVersion,
    QuotaDefinition,
    SubscriptionState,
)

pytestmark = pytest.mark.django_db

FEATURE_KEYS = {
    "seo.audit.enabled",
    "sites.enabled",
    "storage.enabled",
    "notifications.enabled",
    "booking.enabled",
    "medical.enabled",
    "custom_domain.enabled",
}
QUOTA_KEYS = {
    "sites.max",
    "locations.max",
    "team_members.max",
    "storage.bytes",
    "email.monthly",
    "appointments.monthly",
    # The plan's monthly credit allowance is an ordinary quota, so it is
    # versioned with the plan and overridable per organization.
    "credits.monthly",
}


def organization(*, slug: str = "billing-acme") -> Organization:
    return Organization.objects.create(name="Billing ACME", slug=slug)


def actor() -> User:
    return User.objects.create_user(email="billing-operator@example.com")


def tenant_context(tenant: Organization, user: User) -> TenantContext:
    return TenantContext(
        organization_id=tenant.id,
        membership_id=uuid.uuid7(),
        actor_id=user.id,
        role_key="owner",
        permissions=frozenset({"organization.billing.manage"}),
    )


def test_pilot_catalog_is_seeded_with_current_immutable_versions() -> None:
    assert set(Feature.objects.values_list("key", flat=True)) == FEATURE_KEYS
    assert set(QuotaDefinition.objects.values_list("key", flat=True)) == QUOTA_KEYS

    starter = Plan.objects.select_related("current_version").get(key="starter")
    pro = Plan.objects.select_related("current_version").get(key="pro")

    assert starter.current_version is not None
    assert starter.current_version.unit_amount_minor == 14_900
    assert starter.current_version.currency == "PLN"
    assert starter.current_version.trial_days == 3
    assert starter.current_version.grace_period_days == 7
    assert starter.current_version.quotas["sites.max"] == 1
    # Published as a new version rather than edited into the old one, because a
    # published version is immutable in the model and in the database.
    assert starter.current_version.quotas["credits.monthly"] == 200
    assert "custom_domain.enabled" not in starter.current_version.feature_keys
    assert "seo.audit.enabled" not in starter.current_version.feature_keys
    assert pro.current_version is not None
    assert pro.current_version.unit_amount_minor == 29_900
    assert pro.current_version.quotas["storage.bytes"] == 50 * 1024**3
    assert pro.current_version.quotas["credits.monthly"] == 1000
    assert "custom_domain.enabled" in pro.current_version.feature_keys
    assert "seo.audit.enabled" not in pro.current_version.feature_keys


def test_plan_version_rejects_unknown_catalog_keys() -> None:
    candidate = PlanVersion(
        plan=Plan.objects.get(key="starter"),
        version=2,
        unit_amount_minor=15_900,
        feature_keys=["unknown.enabled"],
        quotas={"unknown.max": 1},
    )

    with pytest.raises(ValidationError) as raised:
        candidate.full_clean()

    assert "feature_keys" in raised.value.message_dict
    assert "quotas" in raised.value.message_dict


def test_plan_version_is_immutable_in_model_and_database() -> None:
    version = PlanVersion.objects.get(plan__key="starter", version=1)
    version.unit_amount_minor = 1

    with pytest.raises(ValidationError, match="niemutowalna"):
        version.save()
    with pytest.raises(ValidationError, match="niemutowalna"):
        version.delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        PlanVersion.objects.filter(pk=version.pk).update(unit_amount_minor=1)
    with pytest.raises(DatabaseError), transaction.atomic():
        PlanVersion.objects.filter(pk=version.pk).delete()

    version.refresh_from_db()
    assert version.unit_amount_minor == 14_900


def test_grant_requires_exactly_one_typed_target_and_a_valid_window() -> None:
    tenant = organization()
    feature = Feature.objects.get(key="booking.enabled")
    quota = QuotaDefinition.objects.get(key="appointments.monthly")

    with pytest.raises(IntegrityError), transaction.atomic():
        EntitlementGrant.all_objects.create(
            organization=tenant,
            source=GrantSource.PROMOTION,
            feature=feature,
            quota_definition=quota,
            enabled=True,
            limit_value=10,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        EntitlementGrant.all_objects.create(
            organization=tenant,
            source=GrantSource.PROMOTION,
            feature=feature,
            enabled=True,
            expires_at=timezone.now() - timedelta(days=1),
        )


def test_override_requires_actor_and_reason_at_database_boundary() -> None:
    tenant = organization()
    feature = Feature.objects.get(key="custom_domain.enabled")

    with pytest.raises(IntegrityError), transaction.atomic():
        EntitlementGrant.all_objects.create(
            organization=tenant,
            source=GrantSource.OVERRIDE,
            feature=feature,
            enabled=True,
        )

    grant = EntitlementGrant.all_objects.create(
        organization=tenant,
        source=GrantSource.OVERRIDE,
        feature=feature,
        enabled=True,
        granted_by=actor(),
        reason="Kontrakt pilota",
    )
    assert grant.reason == "Kontrakt pilota"


def test_snapshot_is_local_tenant_scoped_and_validates_values() -> None:
    tenant = organization()
    user = actor()
    version = PlanVersion.objects.get(plan__key="pro", version=1)
    snapshot = EntitlementSnapshot.all_objects.create(
        organization=tenant,
        plan_version=version,
        subscription_state=SubscriptionState.TRIALING,
        access_mode=AccessMode.FULL,
        features={key: True for key in version.feature_keys},
        quotas=version.quotas,
        sources={"plan": f"pro:v{version.version}"},
    )

    with pytest.raises(MissingTenantContext):
        EntitlementSnapshot.objects.count()
    with activate_tenant_context(tenant_context(tenant, user)):
        assert EntitlementSnapshot.objects.get() == snapshot

    invalid = EntitlementSnapshot(
        organization=organization(slug="invalid-snapshot"),
        features={"booking.enabled": "yes"},
        quotas={"appointments.monthly": -1},
    )
    with pytest.raises(ValidationError) as raised:
        invalid.full_clean()
    assert "features" in raised.value.message_dict
    assert "quotas" in raised.value.message_dict


def test_only_one_snapshot_per_organization_is_allowed() -> None:
    tenant = organization()
    EntitlementSnapshot.all_objects.create(organization=tenant)

    with pytest.raises(IntegrityError), transaction.atomic():
        EntitlementSnapshot.all_objects.create(organization=tenant)
