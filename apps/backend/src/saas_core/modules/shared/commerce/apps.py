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
        )
        from saas_core.modules.shared.customers.api import register_customer_anonymizer

        from .orders import holds_amounts, name_orders, strip_buyer

        # The buyer on an order goes when the customer is stripped (ADR-073 §9).
        register_customer_anonymizer("shared.commerce.orders", strip_buyer)
        # A company with orders keeps its currency (ADR-073 §8).
        register_currency_use(holds_amounts)
        # The company's history names an order by its number.
        register_history_target("order", name_orders)
