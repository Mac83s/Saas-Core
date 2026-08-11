from django.apps import AppConfig


class MediaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.media"
    label = "media"
    verbose_name = "Media"
