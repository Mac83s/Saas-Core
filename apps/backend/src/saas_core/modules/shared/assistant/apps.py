from django.apps import AppConfig


class AssistantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.assistant"
    label = "assistant"
    verbose_name = "Asystent AI"

    def ready(self) -> None:
        from saas_core.modules.core.organizations.api import register_setting_group

        from .settings_spec import LIMITS, RETENTION

        # Platform keys in model_port's "ai" area (ADR-078).
        register_setting_group(LIMITS)
        register_setting_group(RETENTION)
        # Conversations and older profile versions leave with the common
        # privacy run, on the platform's days (ADR-078).
        from .retention import register_retention

        register_retention()
