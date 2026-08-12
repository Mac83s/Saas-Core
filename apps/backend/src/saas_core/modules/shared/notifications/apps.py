from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.notifications"
    label = "notifications"
    verbose_name = "Notifications and integrations"

    def ready(self) -> None:
        from saas_core.modules.core.organizations.api import register_domain_event_handler

        from .services import consume_domain_event

        register_domain_event_handler("sites.site.published", 1, consume_domain_event)
