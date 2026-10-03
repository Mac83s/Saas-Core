"""The company's basic settings on the registry (ADR-078, R2b): panel language,
time zone and currency. They stay columns of `Organization` (one version, the
`PATCH …/organizations/current/` and `organization.update@1` they always had),
so the group is an entity group of core itself; the registry adds the
declarations, the schema entry and `resolve()`."""

from __future__ import annotations

from typing import Any

from django.conf import settings

from .context import require_tenant_context
from .models import Organization
from .options import CURRENCIES, DEFAULT_CURRENCY, PANEL_LOCALES
from .permissions import SETTINGS_MANAGE
from .settings_registry import SettingArea, SettingGroup, SettingSpec, schema_entry

#: The company's own areas of „Ustawienia” (answer 33a): its details on their
#: page, its security on the generic one.
COMPANY_AREA = SettingArea(
    key="company",
    title={"pl": "Dane firmy", "en": "Company details"},
    description={
        "pl": "Nazwa, język panelu, strefa czasowa i waluta firmy.",
        "en": "The company's name, panel language, time zone and currency.",
    },
    order=10,
    page="/panel/settings/company",
)
SECURITY_AREA = SettingArea(
    key="security",
    title={"pl": "Bezpieczeństwo", "en": "Security"},
    description={
        "pl": "Kto w firmie musi logować się z weryfikacją dwuetapową (2FA).",
        "en": "Who in the company must sign in with two-factor verification (2FA).",
    },
    order=15,
)


#: Where a company decides how long it keeps personal data of people outside
#: it (answer 37a). The area is core's, because several modules keep such data
#: — booking its customers, the site its enquiries — and each brings its group.
PRIVACY_AREA = SettingArea(
    key="privacy",
    title={"pl": "Prywatność i dane", "en": "Privacy and data"},
    description={
        "pl": "Po jakim czasie firma usuwa dane osobowe klientów i osób, które do niej "
        "napisały. Domyślnie nic nie jest usuwane.",
        "en": "After how long the company removes personal data of its customers and of "
        "people who wrote to it. By default nothing is removed.",
    },
    order=17,
)


def _explicit() -> dict[str, Any]:
    organization = Organization.objects.get(pk=require_tenant_context().organization_id)
    return {
        "default_locale": organization.default_locale,
        "timezone": organization.timezone,
        "currency": organization.currency,
    }


BASICS = SettingGroup(
    key="organization",
    module="core.organizations",
    title={"pl": "Firma", "en": "Company"},
    description={
        "pl": "Język panelu, strefa czasowa i waluta, z których korzystają kalendarz, "
        "wiadomości i nowe dane.",
        "en": "The panel language, time zone and currency the calendar, messages and new data use.",
    },
    permission=SETTINGS_MANAGE,
    area="company",
    api="/api/v1/organizations/current/",
    read_explicit=_explicit,
    settings=(
        SettingSpec(
            key="organization.default_locale",
            type="enum",
            default="pl",
            scopes=("organization",),
            values=tuple((code, PANEL_LOCALES[code]) for code in settings.APP_LOCALES),
            label={"pl": "Język panelu", "en": "Panel language"},
            help={
                "pl": "Język panelu i e-maili do zespołu, gdy osoba nie wybrała swojego.",
                "en": "The language of the panel and of e-mails to the team when a person "
                "has not chosen their own.",
            },
            model_description="The language of the panel and of e-mails to the team (pl or "
            "en); not the language of the company's customers.",
        ),
        SettingSpec(
            key="organization.timezone",
            type="text",
            default="Europe/Warsaw",
            max_length=64,
            scopes=("organization",),
            label={"pl": "Strefa czasowa", "en": "Time zone"},
            help={
                "pl": "W tej strefie liczą się godziny pracy, wizyty i daty dokumentów.",
                "en": "Working hours, visits and document dates follow this time zone.",
            },
            model_description="The company's IANA time zone, e.g. Europe/Warsaw: working "
            "hours, visits and the dates of its documents follow it.",
        ),
        SettingSpec(
            key="organization.currency",
            type="enum",
            default=DEFAULT_CURRENCY,
            scopes=("organization",),
            values=CURRENCIES,
            label={"pl": "Waluta", "en": "Currency"},
            help={
                "pl": "Waluta cen i wyceny magazynu. Pozycja magazynu zachowuje walutę, w "
                "której ją założono.",
                "en": "The currency of prices and stock values. A stock item keeps the "
                "currency it was created in.",
            },
            model_description="The ISO 4217 currency the company keeps its prices and stock "
            "values in. A stock item keeps the currency it was created in.",
        ),
    ),
)


def organization_options() -> dict[str, Any]:
    """What a company may choose for its basic settings, before it exists too."""
    return {"keys": [schema_entry(spec) for spec in BASICS.settings]}
