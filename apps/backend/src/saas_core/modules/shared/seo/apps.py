from django.apps import AppConfig


class SeoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.seo"
    label = "seo"
    verbose_name = "SEO audits"

    def ready(self) -> None:
        from saas_core.modules.core.organizations.erasure_checks import register_erasure_check

        from . import checks  # noqa: F401
        from .gsc.services import erasure_check

        register_erasure_check("shared.seo.gsc", erasure_check)
