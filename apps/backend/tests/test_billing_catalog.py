from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
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

# The assistant's features (billing 0026, ADR-076 pkt 8): known to every
# profile, granted by no plan until `shared.assistant` publishes them.
ASSISTANT_FEATURE_KEYS = {
    "assistant.text.enabled",
    "assistant.site_generation.enabled",
    "assistant.voice.enabled",
}
#: Published to every plan by `shared.assistant` 0004, where it is composed (A3).
ASSISTANT_PUBLISHED = (
    {"assistant.text.enabled"} if apps.is_installed("saas_core.modules.shared.assistant") else set()
)
FEATURE_KEYS = {
    "seo.audit.enabled",
    "seo.gsc.enabled",
    "sites.enabled",
    "storage.enabled",
    "notifications.enabled",
    "booking.enabled",
    "custom_domain.enabled",
} | ASSISTANT_FEATURE_KEYS | {
    # A module outside the pilot catalogue (the farm register, a product's
    # vertical, ADR-049) publishes its own feature from its own migration.
    entitlement
    for module_id in settings.ACTIVE_MODULES
    for entitlement in settings.MODULE_CATALOG[module_id].entitlements
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
    # Pages on one site (billing 0024): Profile 5, Site 15, Pro 50 for now.
    "pages.max",
    # Company templates, sections and pages together (billing 0025): 3, 10, 50.
    "sites.templates.max",
    # Languages beyond the company's first (billing 0028): Profile 1, others none.
    "public_locales.additional.max",
} | (
    # The image generator's attempt limit comes with its module's migration
    # (image_generation 0003), so only a profile composing the module has it.
    {"image_generation.monthly"} if "shared.image-generation" in settings.ACTIVE_MODULES else set()
)


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
    assert starter.current_version.quotas["pages.max"] == 15
    assert starter.current_version.quotas["sites.templates.max"] == 10
    # Published as a new version rather than edited into the old one, because a
    # published version is immutable in the model and in the database.
    assert starter.current_version.quotas["credits.monthly"] == 200
    assert "custom_domain.enabled" not in starter.current_version.feature_keys
    assert "seo.audit.enabled" not in starter.current_version.feature_keys
    assert pro.current_version is not None
    assert pro.current_version.unit_amount_minor == 29_900
    assert pro.current_version.quotas["storage.bytes"] == 50 * 1024**3
    assert pro.current_version.quotas["credits.monthly"] == 1000
    assert pro.current_version.quotas["pages.max"] == 50
    assert pro.current_version.quotas["sites.templates.max"] == 50
    assert "custom_domain.enabled" in pro.current_version.feature_keys
    assert "seo.audit.enabled" not in pro.current_version.feature_keys


def test_template_limits_walk_back_to_the_previous_versions_and_forward_again() -> None:
    """Billing 0025 publishes a version per plan; withdrawing points the plans
    back, and publishing again reuses that version instead of a third one."""
    before = ("billing", "0024_pages_quota")
    after = ("billing", "0025_site_templates_quota")
    published = Plan.objects.get(key="starter").current_version_id

    MigrationExecutor(connection).migrate([before])
    starter = Plan.objects.select_related("current_version").get(key="starter")
    assert "sites.templates.max" not in starter.current_version.quotas
    assert starter.current_version.quotas["pages.max"] == 15
    assert not QuotaDefinition.objects.filter(key="sites.templates.max").exists()

    MigrationExecutor(connection).migrate([after])
    starter = Plan.objects.select_related("current_version").get(key="starter")
    assert starter.current_version_id == published
    assert starter.current_version.quotas["sites.templates.max"] == 10
    profile = Plan.objects.select_related("current_version").get(key="profile")
    assert profile.current_version.quotas["sites.templates.max"] == 3


def test_assistant_features_are_known_and_only_the_published_one_is_in_plans() -> None:
    """Known, so a decision answers feature_disabled and an operator override can
    name them. The text chat is in every plan where `shared.assistant` is
    composed (its migration 0004; answer 23 b); the others are in no plan
    version, current or past. No assistant quota: credits meter it."""
    seeded = Feature.objects.filter(key__in=ASSISTANT_FEATURE_KEYS)
    assert {(feature.key, feature.module, feature.is_active) for feature in seeded} == {
        (key, "shared.assistant", True) for key in ASSISTANT_FEATURE_KEYS
    }
    granted = {key for version in PlanVersion.objects.all() for key in version.feature_keys}
    assert granted & ASSISTANT_FEATURE_KEYS == ASSISTANT_PUBLISHED
    current = [plan.current_version.feature_keys for plan in Plan.objects.all()]
    assert all(set(keys) >= ASSISTANT_PUBLISHED for keys in current)
    assert not QuotaDefinition.objects.filter(key__startswith="assistant.").exists()


def test_assistant_features_walk_back_and_forward_without_touching_plans() -> None:
    """Billing 0026 moves no plan. Walking back deletes a feature nothing names
    and only switches off one an override or a plan version names (the rule of
    `withdraw_feature`); walking forward switches them on again."""
    before = ("billing", "0025_site_templates_quota")
    after = ("billing", "0026_assistant_features")
    if ASSISTANT_PUBLISHED:
        # The assistant's own publication depends on 0026 and does move plans:
        # taken back first, so what is walked here is billing 0026 alone.
        MigrationExecutor(connection).migrate([("assistant", "0003_grant_role_permissions")])
    EntitlementGrant.all_objects.create(
        organization=organization(slug="assistant-pilot"),
        source=GrantSource.OVERRIDE,
        feature=Feature.objects.get(key="assistant.text.enabled"),
        enabled=True,
        granted_by=actor(),
        reason="Pilot asystenta",
    )
    # What rolling back a later `publish_feature` leaves: an immutable version
    # still naming the key, with the plan pointed back at the one before it.
    latest = PlanVersion.objects.filter(plan__key="pro").order_by("-version").first()
    assert latest is not None
    PlanVersion.objects.create(
        plan=latest.plan,
        version=latest.version + 1,
        unit_amount_minor=latest.unit_amount_minor,
        feature_keys=[*latest.feature_keys, "assistant.voice.enabled"],
        quotas=dict(latest.quotas),
    )
    # The plans as 0026 left them: later migrations move plans of their own.
    MigrationExecutor(connection).migrate([after])
    current = dict(Plan.objects.values_list("key", "current_version_id"))

    MigrationExecutor(connection).migrate([before])
    assert dict(Plan.objects.values_list("key", "current_version_id")) == current
    left = Feature.objects.filter(key__in=ASSISTANT_FEATURE_KEYS)
    assert dict(left.values_list("key", "is_active")) == {
        "assistant.text.enabled": False,
        "assistant.voice.enabled": False,
    }

    MigrationExecutor(connection).migrate([after])
    assert dict(Plan.objects.values_list("key", "current_version_id")) == current
    active = Feature.objects.filter(key__in=ASSISTANT_FEATURE_KEYS, is_active=True)
    assert set(active.values_list("key", flat=True)) == ASSISTANT_FEATURE_KEYS


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


def test_a_module_feature_survives_a_rollback_and_a_second_publish() -> None:
    """A module's feature migration run back and forth leaves plans selling it."""
    from django.apps import apps  # noqa: PLC0415

    from saas_core.modules.shared.billing.feature_migrations import (  # noqa: PLC0415
        publish_feature,
        withdraw_feature,
    )

    key = "rollback.enabled"

    def selling() -> set[bool]:
        return {
            key in plan.current_version.feature_keys
            for plan in Plan.objects.select_related("current_version")
        }

    publish_feature(apps, key=key, name="Próba", module="shared.billing")
    assert selling() == {True}
    withdraw_feature(apps, key=key)
    assert selling() == {False}
    assert not Feature.objects.filter(key=key).exists()

    # Published once more: the versions carrying it exist, the plans point back.
    publish_feature(apps, key=key, name="Próba", module="shared.billing")
    assert selling() == {True}

    # An override ever granted on it protects the row: switched off, not deleted.
    EntitlementGrant.all_objects.create(
        organization=organization(slug="rollback-grant"),
        source=GrantSource.OVERRIDE,
        feature=Feature.objects.get(key=key),
        enabled=True,
        granted_by=actor(),
        reason="Pilot",
    )
    withdraw_feature(apps, key=key)
    assert Feature.objects.get(key=key).is_active is False
