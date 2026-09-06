from django.apps import AppConfig


class ProfilesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.profiles"
    label = "profiles"
    verbose_name = "Profile publiczne"
