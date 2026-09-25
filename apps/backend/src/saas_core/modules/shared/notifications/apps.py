from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.notifications"
    label = "notifications"
    verbose_name = "Notifications and integrations"

    def ready(self) -> None:
        from saas_core.modules.core.organizations.api import register_domain_event_handler
        from saas_core.modules.core.organizations.erasure_checks import register_erasure_rows

        from .models import ApiKeyCredentialRoute, ProviderMessageRoute
        from .services import consume_domain_event

        # Pre-tenant lookups keyed by a bare organization id: erased with it.
        register_erasure_rows(
            "shared.notifications.provider_message_route", ProviderMessageRoute, "organization_id"
        )
        register_erasure_rows(
            "shared.notifications.api_key_route", ApiKeyCredentialRoute, "organization_id"
        )

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
