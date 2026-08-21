import uuid

import django.db.models.deletion
import django.db.models.manager
from django.conf import settings
from django.db import migrations, models

CREATE_DOMAIN_ONBOARDING_GUARDS = """
CREATE OR REPLACE FUNCTION sites_validate_domain_onboarding_links()
RETURNS trigger AS $$
BEGIN
    IF TG_TABLE_NAME = 'sites_domain' THEN
        IF (SELECT organization_id FROM sites_site WHERE id = NEW.site_id)
            IS DISTINCT FROM NEW.organization_id THEN
            RAISE EXCEPTION 'domain site belongs to another organization'
                USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'sites_domainmutation' THEN
        IF (SELECT organization_id FROM sites_domain WHERE id = NEW.domain_id)
            IS DISTINCT FROM NEW.organization_id THEN
            RAISE EXCEPTION 'domain mutation belongs to another organization'
                USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'sites_siteonboardingdraft' THEN
        IF NEW.site_id IS NOT NULL
            AND (SELECT organization_id FROM sites_site WHERE id = NEW.site_id)
                IS DISTINCT FROM NEW.organization_id THEN
            RAISE EXCEPTION 'onboarding site belongs to another organization'
                USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'sites_siteonboardingmutation' THEN
        IF (SELECT organization_id FROM sites_siteonboardingdraft WHERE id = NEW.draft_id)
            IS DISTINCT FROM NEW.organization_id THEN
            RAISE EXCEPTION 'onboarding mutation belongs to another organization'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sites_domain_tenant_links
BEFORE INSERT OR UPDATE ON sites_domain
FOR EACH ROW EXECUTE FUNCTION sites_validate_domain_onboarding_links();

CREATE TRIGGER sites_domainmutation_tenant_links
BEFORE INSERT OR UPDATE ON sites_domainmutation
FOR EACH ROW EXECUTE FUNCTION sites_validate_domain_onboarding_links();

CREATE TRIGGER sites_siteonboardingdraft_tenant_links
BEFORE INSERT OR UPDATE ON sites_siteonboardingdraft
FOR EACH ROW EXECUTE FUNCTION sites_validate_domain_onboarding_links();

CREATE TRIGGER sites_siteonboardingmutation_tenant_links
BEFORE INSERT OR UPDATE ON sites_siteonboardingmutation
FOR EACH ROW EXECUTE FUNCTION sites_validate_domain_onboarding_links();

CREATE TRIGGER sites_siteonboardingmutation_append_only
BEFORE UPDATE OR DELETE ON sites_siteonboardingmutation
FOR EACH ROW EXECUTE FUNCTION sites_reject_append_only_mutation();
"""

DROP_DOMAIN_ONBOARDING_GUARDS = """
DROP TRIGGER IF EXISTS sites_siteonboardingmutation_append_only
    ON sites_siteonboardingmutation;
DROP TRIGGER IF EXISTS sites_siteonboardingmutation_tenant_links
    ON sites_siteonboardingmutation;
DROP TRIGGER IF EXISTS sites_siteonboardingdraft_tenant_links
    ON sites_siteonboardingdraft;
DROP TRIGGER IF EXISTS sites_domainmutation_tenant_links ON sites_domainmutation;
DROP TRIGGER IF EXISTS sites_domain_tenant_links ON sites_domain;
DROP FUNCTION IF EXISTS sites_validate_domain_onboarding_links();
"""


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sites", "0004_domain_domainmutation_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="domain",
            name="sites_domain_active_platform_uq",
        ),
        migrations.CreateModel(
            name="SiteOnboardingDraft",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "step",
                    models.CharField(
                        choices=[
                            ("address", "Adres"),
                            ("details", "Podstawowe dane"),
                            ("review", "Podsumowanie"),
                            ("completed", "Zakończony"),
                        ],
                        default="address",
                        max_length=16,
                    ),
                ),
                ("name", models.CharField(blank=True, max_length=160)),
                ("subdomain_label", models.CharField(blank=True, max_length=63)),
                (
                    "default_locale",
                    models.CharField(
                        choices=[("pl", "Polski"), ("en", "English")],
                        default="pl",
                        max_length=10,
                    ),
                ),
                ("version", models.PositiveBigIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_site_onboarding_drafts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="organizations.organization",
                    ),
                ),
                (
                    "site",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="onboarding_draft",
                        to="sites.site",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="updated_site_onboarding_drafts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("organization_id", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization",),
                        name="sites_onboarding_org_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(step="completed", site__isnull=False)
                            | (~models.Q(step="completed") & models.Q(site__isnull=True))
                        ),
                        name="sites_onboarding_completion_ck",
                    ),
                ],
            },
            managers=[
                ("all_objects", django.db.models.manager.Manager()),
            ],
        ),
        migrations.CreateModel(
            name="SiteOnboardingMutation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("idempotency_key", models.CharField(max_length=120)),
                ("request_hash", models.CharField(max_length=64)),
                ("resulting_version", models.PositiveBigIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="site_onboarding_mutations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "draft",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="mutations",
                        to="sites.siteonboardingdraft",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="organizations.organization",
                    ),
                ),
            ],
            options={
                "ordering": ("organization_id", "created_at", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "actor", "idempotency_key"),
                        name="sites_onboarding_mutation_idem_uq",
                    )
                ],
            },
            managers=[
                ("all_objects", django.db.models.manager.Manager()),
            ],
        ),
        migrations.RunSQL(
            sql=CREATE_DOMAIN_ONBOARDING_GUARDS,
            reverse_sql=DROP_DOMAIN_ONBOARDING_GUARDS,
        ),
    ]
