from pathlib import Path

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, register


class ProfilesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.profiles"
    label = "profiles"
    verbose_name = "Profile publiczne"

    def ready(self) -> None:
        register(check_catalog_contract, "profiles")


def check_catalog_contract(**_kwargs: object) -> list[Error]:
    """Fails the deploy when the catalogue dictionary did not reach the image.

    The city and category lists are read from disk on first use, so a missing
    directory would surface as a 500 the first time somebody opens the catalogue
    — long after the deploy reported success.
    """
    directory = Path(settings.CATALOG_CONTRACTS_PATH)
    if (directory / "manifest.json").is_file():
        return []
    return [
        Error(
            "CATALOG_CONTRACTS_PATH nie wskazuje na katalog z manifest.json.",
            hint=(
                "Skopiuj packages/contracts/catalog do obrazu i ustaw zmienną "
                "środowiskową CATALOG_CONTRACTS_PATH."
            ),
            obj=str(directory),
            id="profiles.E001",
        )
    ]
