from django.apps import AppConfig


class SeoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.seo"
    label = "seo"
    verbose_name = "SEO audits"

    def ready(self) -> None:
        from . import checks  # noqa: F401
