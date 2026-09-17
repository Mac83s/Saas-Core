from django.apps import AppConfig


class MedicalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.vertical.medical"
    label = "medical"
    verbose_name = "Medical"
