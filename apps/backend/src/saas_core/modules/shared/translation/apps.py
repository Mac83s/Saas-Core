from django.apps import AppConfig


class TranslationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.translation"
    label = "translation"
    verbose_name = "Tłumaczenia AI"

    def ready(self) -> None:
        from saas_core.content_protocol.registry import register_translation_policy

        from . import checks  # noqa: F401 — registers the system checks
        from .engine_policy import ENGINE_POLICY

        register_translation_policy(ENGINE_POLICY)

        from saas_core.modules.shared.model_port.api import register_task

        from .command_declarations import register_translation_commands
        from .evals.runner import JUDGE_SPEC
        from .notify import register_templates

        register_translation_commands()
        register_templates()
        register_task(JUDGE_SPEC)
