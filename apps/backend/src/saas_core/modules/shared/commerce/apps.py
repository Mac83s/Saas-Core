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
            register_retention_sweep,
            register_service_scope,
        )
        from saas_core.modules.core.organizations.erasure_checks import register_erasure_rows
        from saas_core.modules.shared.customers.api import (
            register_customer_anonymizer,
            register_customer_viewer,
        )

        from .balance import register_balance_settings
        from .command_declarations import register_commerce_commands
        from .emails import register_templates
        from .models import PaymentRoute
        from .names import DEADLINES_PERMISSIONS, DEADLINES_ROLE
        from .orders import holds_amounts, name_orders, strip_buyer
        from .people import buyers_of_orders
        from .retention import BUYERS, kept_of
        from .transfer_account import register_transfer_settings

        # The buyer on an order goes when the customer is stripped (ADR-073
        # §9) — by hand or by the company's removal after a time, the same
        # way — except on a sales record inside its period (slice 4i), which
        # `kept_of` names to whoever asks before they strip. Commerce holds
        # no customer back from that removal (the owner's answer of 04.10).
        register_customer_anonymizer("shared.commerce.orders", strip_buyer, keeps=kept_of)
        # The nightly privacy run removes a buyer left on an order of a
        # stripped customer, once its period has ended.
        register_retention_sweep(BUYERS)
        # Whose card the assistant's conversation may show: whoever reads orders
        # reads their buyers.
        register_customer_viewer("orders", buyers_of_orders)
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
        # A demo company's bank account, before its offers ask for a transfer,
        # and what happens to an order's money in a demo story (seed_demo).
        from saas_core.modules.core.organizations.demo import register_demo_part

        from .demo import describe, register_steps, seed_transfer_accounts

        register_demo_part(
            "commerce.transfer", seed_transfer_accounts, order=20, describe=describe
        )
        register_steps()
