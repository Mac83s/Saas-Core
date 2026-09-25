from django.apps import AppConfig


class ImageGenerationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.image_generation"
    label = "image_generation"
    verbose_name = "Generowanie obrazów"
