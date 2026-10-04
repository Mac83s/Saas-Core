from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.notifications"
    label = "notifications"
    verbose_name = "Notifications and integrations"

    def ready(self) -> None:
        from saas_core.modules.core.organizations.api import register_domain_event_handler
        from saas_core.modules.core.organizations.erasure_checks import register_erasure_rows

        from .customer_mail import register_customer_mail
        from .models import ApiKeyCredentialRoute, ProviderMessageRoute
        from .retention_notice import register_retention_notice
        from .services import consume_domain_event

        # Pre-tenant lookups keyed by a bare organization id: erased with it.
        # The owners hear when a removal of personal data is switched on (37a).
        register_retention_notice()
        register_erasure_rows(
            "shared.notifications.provider_message_route", ProviderMessageRoute, "organization_id"
        )
        register_erasure_rows(
            "shared.notifications.api_key_route", ApiKeyCredentialRoute, "organization_id"
        )
        # Whom customers hear from and the company's note to them (36a, ADR-078).
        register_customer_mail()
        # How many messages a demo run queued: counted before every other part
        # and said after the last one (seed_demo).
        from saas_core.modules.core.organizations.demo import register_demo_part

        from .demo import count_before, report

        register_demo_part("notifications.count", count_before, order=1)
        register_demo_part("notifications.report", report, order=990)

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
