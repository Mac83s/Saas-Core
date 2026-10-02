from django.apps import AppConfig


class TranslationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.translation"
    label = "translation"
    verbose_name = "Tłumaczenia AI"
