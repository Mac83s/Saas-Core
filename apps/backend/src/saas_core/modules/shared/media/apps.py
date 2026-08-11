from django.apps import AppConfig


class MediaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.media"
    label = "media"
    verbose_name = "Media"

    def ready(self) -> None:
        from saas_core.modules.core.organizations.api import (
            register_resource_reference_handler,
        )

        from .references import MEDIA_ASSET_RESOURCE_TYPE, media_asset_reference_handler

        register_resource_reference_handler(
            MEDIA_ASSET_RESOURCE_TYPE,
            media_asset_reference_handler,
        )
