from django.apps import AppConfig
from django.db.models.signals import post_migrate


class OrganizationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.core.organizations"
    label = "organizations"
    verbose_name = "Organizations"

    def ready(self) -> None:
        # ADR-050: the product's system roles follow its catalogue after every
        # migrate, which runs under the role that owns the tables.
        from .role_catalog import sync_after_migrate  # noqa: PLC0415

        post_migrate.connect(sync_after_migrate, sender=self)
