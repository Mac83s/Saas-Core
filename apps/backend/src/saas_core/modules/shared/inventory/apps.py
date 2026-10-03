from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.inventory"
    label = "inventory"
    verbose_name = "Inventory"

    def ready(self) -> None:
        from django.apps import apps

        from saas_core.modules.core.organizations.demo import register_demo_part

        from .alerts import register_templates
        from .company_settings import register_company_settings
        from .demo import seed_warehouse

        # Stock and movements for a demo organization (seed_demo).
        register_demo_part("inventory.warehouse", seed_warehouse, order=40)
        # Low-stock notices, lot expiry and where a visit's products come from (ADR-078).
        register_company_settings()
        register_templates()
        # The company's history names a document and an item (UX-055).
        from .history_targets import register_history_targets

        register_history_targets()

        # A person's card shows what they took and used — where there are cards.
        if apps.is_installed("saas_core.modules.shared.booking"):
            from .facts import register

            register()
