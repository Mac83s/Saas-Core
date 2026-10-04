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
            register_retention_exclusion,
            register_retention_sweep,
            register_service_scope,
        )
        from saas_core.modules.core.organizations.erasure_checks import register_erasure_rows
        from saas_core.modules.shared.customers.api import (
            CUSTOMER_RETENTION_SWEEP,
            register_customer_anonymizer,
        )

        from .balance import register_balance_settings
        from .command_declarations import register_commerce_commands
        from .emails import register_templates
        from .models import PaymentRoute
        from .names import DEADLINES_PERMISSIONS, DEADLINES_ROLE
        from .orders import holds_amounts, name_orders, strip_buyer
        from .retention import BUYERS, WHY_CUSTOMER_STAYS, customers_held, kept_of
        from .transfer_account import register_transfer_settings

        # The buyer on an order goes when the customer is stripped (ADR-073
        # §9) — except on a sales record inside its period (slice 4i), which
        # `kept_of` names to whoever asks before they strip.
        register_customer_anonymizer("shared.commerce.orders", strip_buyer, keeps=kept_of)
        # The company's removal of customers after a time leaves the buyer of
        # such a record alone until the period ends…
        register_retention_exclusion(
            CUSTOMER_RETENTION_SWEEP, customers_held, why=WHY_CUSTOMER_STAYS
        )
        # …and the nightly privacy run removes a buyer left on an order of a
        # customer taken out by hand, once it has ended.
        register_retention_sweep(BUYERS)
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
        # What the assistant may read and mark: orders and payments (ADR-076).
        register_commerce_commands()
        # A pre-tenant routing index: erasing the organization takes it too.
        register_erasure_rows("shared.commerce.payment_route", PaymentRoute, "organization_id")
