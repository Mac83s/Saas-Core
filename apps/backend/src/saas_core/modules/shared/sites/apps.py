from django.apps import AppConfig


class SitesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.sites"
    label = "sites"
    verbose_name = "Sites and content"
