from pathlib import Path

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, register


class SitesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "saas_core.modules.shared.sites"
    label = "sites"
    verbose_name = "Sites and content"

    def ready(self) -> None:
        from .inquiry_emails import register_inquiry_email

        register_inquiry_email()
        register(check_content_contracts, "sites")


def check_content_contracts(**_kwargs: object) -> list[Error]:
    """Fails the deploy when a contract directory did not reach the image.

    Both the block schemas and the template recipes are read from disk on first
    use, so a missing directory surfaces as a 500 the first time an operator
    clicks — long after the deploy reported success. `manage.py check` runs
    before the workers start, which is where this belongs.
    """
    expected = {
        "SITE_BLOCK_CONTRACTS_PATH": (
            settings.SITE_BLOCK_CONTRACTS_PATH,
            "sites.E001",
        ),
        "PAGE_TEMPLATE_CONTRACTS_PATH": (
            settings.PAGE_TEMPLATE_CONTRACTS_PATH,
            "sites.E002",
        ),
        "CONTENT_OPERATIONS_CONTRACTS_PATH": (
            settings.CONTENT_OPERATIONS_CONTRACTS_PATH,
            "sites.E003",
        ),
    }
    errors: list[Error] = []
    for name, (value, code) in expected.items():
        directory = Path(value)
        if not (directory / "manifest.json").is_file():
            errors.append(
                Error(
                    f"{name} nie wskazuje na katalog z manifest.json.",
                    hint=(
                        "Skopiuj katalog kontraktów do obrazu i ustaw zmienną "
                        f"środowiskową {name}."
                    ),
                    obj=str(directory),
                    id=code,
                )
            )
    if any(
        not (
            Path(settings.SITE_BLOCK_CONTRACTS_PATH) / f"site-appearance.v{version}.schema.json"
        ).is_file()
        for version in (1, 2)
    ):
        errors.append(Error("Brak kontraktu wyglądu witryny.", id="sites.E004"))
    if (Path(settings.PAGE_TEMPLATE_CONTRACTS_PATH) / "manifest.json").is_file() and not (
        Path(settings.PAGE_TEMPLATE_CONTRACTS_PATH) / "sample-media.v1.json"
    ).is_file():
        errors.append(Error("Brak katalogu zdjęć szablonów.", id="sites.E005"))
    if not (
        Path(settings.SITE_BLOCK_CONTRACTS_PATH) / "section-decoration.v1.schema.json"
    ).is_file():
        errors.append(Error("Brak kontraktu dekoracji sekcji.", id="sites.E006"))
    return errors
