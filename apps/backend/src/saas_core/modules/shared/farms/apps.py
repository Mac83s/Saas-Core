from django.apps import AppConfig


class FarmsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.farms"
    label = "farms"
    verbose_name = "Farms"

    def ready(self) -> None:
        from saas_core.modules.core.organizations.demo import register_demo_part

        from .demo import seed_farm_links

        # A company's farm card linked to the farmer's account (seed_demo).
        register_demo_part("farms.link", seed_farm_links, order=20)
        # The company's history names the farm a row is about (UX-055).
        from .history_targets import register_history_targets

        register_history_targets()
