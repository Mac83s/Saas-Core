from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.billing"
    label = "billing"
    verbose_name = "Billing and entitlements"
