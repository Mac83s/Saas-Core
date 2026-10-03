from django.apps import AppConfig


class CustomersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.customers"
    label = "customers"
    verbose_name = "Klienci firm"

    def ready(self) -> None:
        from saas_core.modules.core.organizations.erasure_checks import register_erasure_rows

        from .command_declarations import register_customer_commands
        from .models import DocumentRoute

        # A pre-tenant routing index: erasing the organization takes it too.
        register_erasure_rows("shared.customers.document_route", DocumentRoute, "organization_id")
        # What the assistant may read and draft here (ADR-076 §1).
        register_customer_commands()
