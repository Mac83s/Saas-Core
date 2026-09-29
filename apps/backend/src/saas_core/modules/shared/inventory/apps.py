from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.inventory"
    label = "inventory"
    verbose_name = "Inventory"

    def ready(self) -> None:
        from django.apps import apps

        # A person's card shows what they took and used — where there are cards.
        if apps.is_installed("saas_core.modules.shared.booking"):
            from .facts import register

            register()
