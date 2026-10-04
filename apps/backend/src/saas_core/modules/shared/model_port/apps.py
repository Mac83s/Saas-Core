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
        from .models import TestDoubleCompany, UsageEntry
        from .service import register_adapter

        register_adapter(OpenRouterAdapter())
        if settings.APP_ENV in {"test", "local"} or settings.MODEL_PORT_TEST_DOUBLE:
            from .adapters.fake import FAKE

            register_adapter(FAKE)
        from . import test_double

        if test_double.enabled():
            # The stand-in translator of browser tests: its model exists only
            # where the stack asks for it by name (`test_double`).
            from .matrix import register_model

            register_model(test_double.echo_profile())
        register_erasure_rows("shared.model-port.usage", UsageEntry, "organization_id")
        # A browser test's company leaves the stand-in's list with the company.
        register_erasure_rows("shared.model-port.test-double", TestDoubleCompany, "organization_id")

        # The tasks' models as platform settings (TL22).
        from saas_core.modules.core.organizations.api import (
            register_setting_area,
            register_setting_group,
        )

        from .settings_spec import AI_AREA, PRIVACY, TASKS

        register_setting_area(AI_AREA)
        register_setting_group(TASKS)
        # Which hosts may be sent a request: none that collects it, by default.
        register_setting_group(PRIVACY)
