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
        # The company's own assistant commands (ADR-076, A1b-9).
        from .command_declarations import register_organization_commands  # noqa: PLC0415

        register_organization_commands()
        # The plan's word on a settings group, before its commands run (ADR-078 pkt 1).
        from .command_executor import register_command_gate  # noqa: PLC0415
        from .settings_commands import settings_gate  # noqa: PLC0415

        register_command_gate("settings", settings_gate)
