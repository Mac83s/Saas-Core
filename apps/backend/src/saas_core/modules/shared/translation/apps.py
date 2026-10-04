from django.apps import AppConfig


class TranslationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.translation"
    label = "translation"
    verbose_name = "Tłumaczenia AI"

    def ready(self) -> None:
        from saas_core.content_protocol.registry import (
            register_review_closer,
            register_review_reader,
            register_source_change_listener,
            register_translation_policy,
        )
        from saas_core.modules.core.organizations.api import (
            register_setting_area,
            register_setting_group,
        )

        from .demand import on_source_change
        from .engine_policy import ENGINE_POLICY
        from .settings_spec import ENGINE, LANGUAGES_AREA, PRICING, SETTINGS

        register_translation_policy(ENGINE_POLICY)
        register_source_change_listener(on_source_change)
        # A module's own list offers the decision where the result stands (TL16g).
        from .review import close_decided_elsewhere, waiting_reviews

        register_review_reader(waiting_reviews)
        # …and a decision taken in a source's own editor closes the queue's item.
        register_review_closer(close_decided_elsewhere)
        # The registry checks the profile's settingsDefaults for these keys at
        # start, and organizations.E101 any other translation.* key.
        register_setting_area(LANGUAGES_AREA)
        register_setting_group(SETTINGS)
        # The price as a platform setting (TL22), in model_port's "ai" area.
        register_setting_group(PRICING)
        # The engine's waits, quality thresholds and confirmation amount (TL22).
        register_setting_group(ENGINE)

        from saas_core.modules.core.organizations.api import platform_setting
        from saas_core.modules.shared.billing.api import (
            register_credit_cost,
            register_credit_subject,
        )

        from .jobs import job_of_hold
        from .permissions import CREDIT_OPERATION
        from .settings_spec import PRICE

        register_credit_cost(CREDIT_OPERATION, lambda: int(platform_setting(PRICE.key)))
        # A row of the credits page leads to the job it paid for (TL16f).
        register_credit_subject(CREDIT_OPERATION, job_of_hold)

        from saas_core.modules.shared.model_port.api import register_task

        from .command_declarations import register_translation_commands
        from .evals.runner import JUDGE_SPEC
        from .notify import register_templates

        register_translation_commands()
        register_templates()
        register_task(JUDGE_SPEC)
        # The notices go as the organization's own job (ADR-073 §5).
        from saas_core.modules.core.organizations.api import register_service_scope

        from .notify import NOTIFY_ROLE

        register_service_scope(NOTIFY_ROLE)
