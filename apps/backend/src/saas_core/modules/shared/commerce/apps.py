from django.apps import AppConfig


class CommerceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.commerce"
    label = "commerce"
    verbose_name = "Zamówienia klientów firm"

    def ready(self) -> None:
        from saas_core.modules.core.organizations.api import (
            register_currency_use,
            register_history_target,
            register_service_scope,
        )
        from saas_core.modules.core.organizations.erasure_checks import register_erasure_rows
        from saas_core.modules.shared.customers.api import register_customer_anonymizer

        from .balance import register_balance_settings
        from .emails import register_templates
        from .models import PaymentRoute
        from .names import DEADLINES_PERMISSIONS, DEADLINES_ROLE
        from .orders import holds_amounts, name_orders, strip_buyer
        from .transfer_account import register_transfer_settings

        # The buyer on an order goes when the customer is stripped (ADR-073 §9).
        register_customer_anonymizer("shared.commerce.orders", strip_buyer)
        # A company with orders keeps its currency (ADR-073 §8).
        register_currency_use(holds_amounts)
        # The company's history names an order by its number.
        register_history_target("order", name_orders)
        # The company's bank account for its customers' transfers (ADR-073 §5).
        register_transfer_settings()
        # When a customer is reminded of the rest of a price due by a transfer.
        register_balance_settings()
        # The transfer's details, sent to the buyer.
        register_templates()
        # The deadlines' task acts as the organization's own job, for one purpose.
        register_service_scope(DEADLINES_ROLE, DEADLINES_PERMISSIONS, exact=True)
        # A pre-tenant routing index: erasing the organization takes it too.
        register_erasure_rows("shared.commerce.payment_route", PaymentRoute, "organization_id")
