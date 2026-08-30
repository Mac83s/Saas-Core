from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.notifications"
    label = "notifications"
    verbose_name = "Notifications and integrations"

    def ready(self) -> None:
        from saas_core.modules.core.organizations.api import register_domain_event_handler

        from .services import consume_domain_event

        # Every type here needs a payload allowlist in `services.py` as well:
        # an unregistered event is silently delivered nowhere, and an
        # unallowlisted one stops the delivery instead.
        for event_type in (
            "sites.site.published",
            "sites.site.rolled_back",
            "sites.entry.published",
            "sites.page.draft_saved",
            "sites.entry.draft_saved",
            "sites.automation_grant.revoked",
        ):
            register_domain_event_handler(event_type, 1, consume_domain_event)
