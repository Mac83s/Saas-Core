from django.apps import AppConfig


class ModelPortConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.model_port"
    label = "model_port"
    verbose_name = "Port modeli AI"

    def ready(self) -> None:
        from django.conf import settings

        from saas_core.modules.core.organizations.erasure_checks import register_erasure_rows

        from . import checks  # noqa: F401 — registers the system checks
        from .adapters.openrouter import OpenRouterAdapter
        from .models import UsageEntry
        from .service import register_adapter

        register_adapter(OpenRouterAdapter())
        if settings.APP_ENV in {"test", "local"}:
            from .adapters.fake import FAKE

            register_adapter(FAKE)
        register_erasure_rows("shared.model-port.usage", UsageEntry, "organization_id")

        # The tasks' models as platform settings (TL22).
        from saas_core.modules.core.organizations.api import (
            register_setting_area,
            register_setting_group,
        )

        from .settings_spec import AI_AREA, TASKS

        register_setting_area(AI_AREA)
        register_setting_group(TASKS)
