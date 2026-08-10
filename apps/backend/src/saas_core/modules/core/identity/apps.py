from django.apps import AppConfig


class IdentityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.core.identity"
    label = "identity"
    verbose_name = "Identity"
