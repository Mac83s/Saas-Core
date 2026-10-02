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
        from django.db.models.signals import post_delete, post_save

        from saas_core.modules.core.organizations.api import register_public_locales_guard

        from .company_locales import profile_locale_problems
        from .models import CatalogEntry
        from .search_index import follow_catalog_entry

        register(check_catalog_contract, "profiles")
        register_public_locales_guard(profile_locale_problems)

        # A page built from a template calls the business card's own phone and
        # writes to its own e-mail, not the template's samples (UX-038).
        from saas_core.modules.shared.sites.api import register_company_contact

        from .api import business_card_contact

        register_company_contact(business_card_contact)

        # The business card's commands for the assistant (ADR-076, A1b-10).
        from .command_declarations import register_profile_commands

        register_profile_commands()

        # Every write of a catalogue row — publication, refresh, withdrawal and
        # the cascade when a company is erased — moves its search document too.
        post_save.connect(
            follow_catalog_entry, sender=CatalogEntry, dispatch_uid="profiles.search.save"
        )
        post_delete.connect(
            follow_catalog_entry, sender=CatalogEntry, dispatch_uid="profiles.search.delete"
        )


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
