"""The billing module, the one signal it listens to and the seat limit it gives.

A new organization gets the free plan of its type right away (ADR-050): the
register has to work before anybody buys anything, and `core.organizations`
may not call billing — the dependency goes the other way.
"""

from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.billing"
    label = "billing"
    verbose_name = "Billing and entitlements"

    def ready(self) -> None:
        from django.db.models.signals import post_save  # noqa: PLC0415

        from saas_core.modules.core.organizations.api import (  # noqa: PLC0415
            register_seat_limit,
        )
        from saas_core.modules.core.organizations.models import (  # noqa: PLC0415
            Organization,
        )

        from .seats import team_members_limit  # noqa: PLC0415
        from .signals import grant_free_plan_on_create  # noqa: PLC0415

        post_save.connect(
            grant_free_plan_on_create,
            sender=Organization,
            dispatch_uid="billing.grant_free_plan_on_create",
        )
        # An invitation takes a seat of the plan; Core asks through this.
        register_seat_limit(team_members_limit)
