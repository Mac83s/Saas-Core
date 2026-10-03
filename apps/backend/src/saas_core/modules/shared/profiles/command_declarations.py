"""The assistant's commands for the company's business card (ADR-076 §1, A1b-10).

Thin adapters over the services the panel's Wizytówka calls (ADR-053). Editing
a card that is in the public catalogue changes the catalogue at once, so such
an edit is a publication and takes a click of its own; putting the card in the
catalogue and taking it out are publications too.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rest_framework.exceptions import ValidationError

from saas_core.modules.core.organizations.api import CommandSpec, Effect, Preview, register_command
from saas_core.modules.core.organizations.models import Organization

from .catalog import ProfileNotPublishable, publish_profile, publishable, withdraw_profile
from .catalog_contract import categories, cities
from .permissions import PROFILES_ENABLED, PROFILES_MANAGE
from .services import (
    CONTACT_FIELDS,
    existing_organization_profile,
    organization_profile,
    planned_organization_profile,
    update_profile,
)

#: What the assistant may write on the card. Photo, links, layout and
#: language stay the panel's for now.
_FIELDS = (
    "display_name",
    "headline",
    "bio",
    "contact_email",
    "contact_phone",
    "contact_address",
    "city_slug",
    "category",
)
_LABELS = {
    "display_name": ("Nazwa", "Name"),
    "headline": ("Jedno zdanie o firmie", "One line about the company"),
    "bio": ("Opis", "Description"),
    "contact_email": ("E-mail kontaktowy", "Contact e-mail"),
    "contact_phone": ("Telefon kontaktowy", "Contact phone"),
    "contact_address": ("Adres", "Address"),
    "city_slug": ("Miasto", "City"),
    "category": ("Kategoria", "Category"),
}
_DESCRIPTIONS = {
    "display_name": "The company's name on its card, up to 160 characters.",
    "headline": "One sentence about the company, up to 200 characters; empty clears it.",
    "bio": "A description of the company, up to 4000 characters; empty clears it.",
    "contact_email": "A public contact e-mail; empty clears it.",
    "contact_phone": "A public contact phone number; empty clears it.",
    "contact_address": "A public address, up to 240 characters; empty clears it.",
    "city_slug": "The town, as a catalogue city slug from profiles.organization.read.",
    "category": "The kind of business, as a catalogue category from profiles.organization.read.",
}
_CARD = {
    "type": "object",
    "x-data-class": "public",
    "properties": {
        "exists": {"type": "boolean"},
        "in_catalog": {"type": "boolean"},
        "version": {"type": "integer"},
        "display_name": {"type": "string"},
        "headline": {"type": "string"},
        "bio": {"type": "string"},
        # Public on the card, but a person's details on a small company's.
        "contact_email": {"type": "string", "x-data-class": "public_personal"},
        "contact_phone": {"type": "string", "x-data-class": "public_personal"},
        "contact_address": {"type": "string", "x-data-class": "public_personal"},
        "city_slug": {"type": "string"},
        "category": {"type": "string"},
        "cities": {"type": "array"},
        "categories": {"type": "array"},
    },
}


def _card(profile: Any, *, exists: bool, in_catalog: bool) -> dict[str, Any]:
    return {
        "exists": exists,
        "in_catalog": in_catalog,
        "version": profile.version if exists else 0,
        **{field: getattr(profile, field) for field in _FIELDS},
    }


def _read(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    profile, in_catalog = existing_organization_profile()
    if profile is None:
        card = {"exists": False, "in_catalog": False, "version": 0, **dict.fromkeys(_FIELDS, "")}
    else:
        card = _card(profile, exists=True, in_catalog=in_catalog)
    organization_type = _organization_type(call)
    return {
        **card,
        "cities": sorted(cities()),
        "categories": sorted(categories(organization_type)),
    }


def _organization_type(call: Any) -> str:
    return str(
        Organization.objects.filter(pk=call.context.organization_id)
        .values_list("organization_type", flat=True)
        .first()
        or ""
    )


def _changes(arguments: Mapping[str, Any]) -> dict[str, Any]:
    changes = {field: arguments[field] for field in _FIELDS if arguments[field] is not None}
    if not changes:
        raise ValidationError("Podaj co najmniej jedno pole do zmiany.")
    return changes


def _resource(call: Any) -> str:
    return f"profiles.organization_card:{call.context.organization_id}"


def _preview_update(arguments: Mapping[str, Any], call: Any) -> Preview:
    _planned, version, diffs, in_catalog = planned_organization_profile(changes=_changes(arguments))

    def line(index: int) -> str:
        return "; ".join(
            # Contact details are named, not repeated.
            _LABELS[field][index]
            if field in CONTACT_FIELDS
            else f"{_LABELS[field][index]}: {old or '—'} → {new or '—'}"
            for field, (old, new) in diffs.items()
        )

    created = (
        ("Wizytówka zostanie założona. ", "The card will be created. ")
        if version == 0
        else ("", "")
    )
    effects = (
        Effect(
            kind="created" if version == 0 else "updated",
            resource="profiles.organization_card",
            resource_id="" if version == 0 else str(_planned.id),
            summary={"pl": created[0] + line(0), "en": created[1] + line(1)},
        ),
    )
    return Preview(
        effects=effects,
        observed_versions={_resource(call): version},
        # In the catalogue the edit is public the moment it is saved.
        escalate_to="publish" if in_catalog else None,
    )


def _update(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    version = call.preview.observed_versions[_resource(call)]
    # A company without a card gets one first, as the panel's first visit does;
    # the consent saw version 0, so the new card's own version is the one to edit.
    profile = organization_profile()
    expected = profile.version if version == 0 else version
    saved = update_profile(profile.id, expected_version=expected, **_changes(arguments))
    _profile, in_catalog = existing_organization_profile()
    return _card(saved, exists=True, in_catalog=in_catalog)


def _publish_preview(arguments: Mapping[str, Any], call: Any) -> Preview:
    profile, in_catalog = existing_organization_profile()
    if profile is None or not publishable(profile):
        raise ProfileNotPublishable
    return Preview(
        effects=(
            Effect(
                kind="published",
                resource="profiles.catalog_entry",
                resource_id=str(profile.id),
                summary={
                    "pl": f"„{profile.display_name}” w katalogu firm: {profile.city_slug}, "
                    f"{profile.category}" + (" (odświeżenie wpisu)" if in_catalog else ""),
                    "en": f"“{profile.display_name}” in the company directory: "
                    f"{profile.city_slug}, {profile.category}"
                    + (" (entry refreshed)" if in_catalog else ""),
                },
            ),
        ),
        observed_versions={_resource(call): profile.version},
    )


def _publish(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    entry = publish_profile()
    return {"in_catalog": True, "slug": entry.slug, "city_slug": entry.city_slug}


def _withdraw_preview(arguments: Mapping[str, Any], call: Any) -> Preview:
    profile, in_catalog = existing_organization_profile()
    effects = (
        (
            Effect(
                kind="withdrawn",
                resource="profiles.catalog_entry",
                resource_id=str(profile.id),
                summary={
                    "pl": f"„{profile.display_name}” znika z katalogu firm",
                    "en": f"“{profile.display_name}” leaves the company directory",
                },
            ),
        )
        if profile is not None and in_catalog
        else ()
    )
    return Preview(
        effects=effects,
        observed_versions={_resource(call): profile.version if profile is not None else 0},
    )


def _withdraw(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    withdraw_profile()
    return {"in_catalog": False, "slug": "", "city_slug": ""}


_NO_INPUT = {"type": "object", "additionalProperties": False, "required": [], "properties": {}}
_CATALOG_OUTPUT = {
    "type": "object",
    "x-data-class": "public",
    "properties": {
        "in_catalog": {"type": "boolean"},
        "slug": {"type": "string"},
        "city_slug": {"type": "string"},
    },
}

CARD_READ = CommandSpec(
    name="profiles.organization.read",
    version=1,
    module="shared.profiles",
    title={"pl": "Odczytaj wizytówkę firmy", "en": "Read the company card"},
    summary={
        "pl": "Wizytówka firmy, czy jest w katalogu, oraz dozwolone miasta i kategorie.",
        "en": "The company card, whether it is in the directory, and allowed towns and kinds.",
    },
    model_description=(
        "Returns the company's public business card (name, one-line headline, description, "
        "contact details, town, kind of business), whether it exists yet, whether it is in "
        "the public company directory, its version, and the towns and categories the "
        "directory accepts. Use it before changing or publishing the card."
    ),
    input_schema=_NO_INPUT,
    output_schema=_CARD,
    permission=PROFILES_MANAGE,
    risk="read",
    run=_read,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)

CARD_UPDATE = CommandSpec(
    name="profiles.organization.update",
    version=1,
    module="shared.profiles",
    title={"pl": "Zmień wizytówkę firmy", "en": "Change the company card"},
    summary={
        "pl": "Nazwa, opis, kontakt, miasto i kategoria na wizytówce.",
        "en": "Name, description, contact, town and kind on the card.",
    },
    model_description=(
        "Changes the company's business card: name, one-line headline, description, "
        "contact e-mail, phone and address, town and category. Pass null for every field "
        "that stays as it is and an empty string to clear one; at least one field must "
        "change. A company without a card gets one. If the card is in the public directory "
        "the change is public at once and needs its own confirmation."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": list(_FIELDS),
        "properties": {
            field: {"type": ["string", "null"], "description": _DESCRIPTIONS[field]}
            for field in _FIELDS
        },
    },
    output_schema=_CARD,
    permission=PROFILES_MANAGE,
    risk="draft",
    run=_update,
    undo="command:profiles.organization.update@1",
    preview=_preview_update,
    version_field="expected_version",
)

CATALOG_PUBLISH = CommandSpec(
    name="profiles.catalog.publish",
    version=1,
    module="shared.profiles",
    title={"pl": "Pokaż wizytówkę w katalogu firm", "en": "Put the card in the directory"},
    summary={
        "pl": "Wizytówka staje się widoczna w publicznym katalogu firm.",
        "en": "The card becomes visible in the public company directory.",
    },
    model_description=(
        "Puts the company's card in the public company directory, under its town and "
        "category; a card already there is refreshed. The card needs a name, a town and a "
        "category first."
    ),
    input_schema=_NO_INPUT,
    output_schema=_CATALOG_OUTPUT,
    permission=PROFILES_MANAGE,
    entitlement=PROFILES_ENABLED,
    risk="publish",
    run=_publish,
    undo="command:profiles.catalog.withdraw@1",
    preview=_publish_preview,
    no_version_reason="Publication puts the card as it is; it changes none of its fields.",
)

CATALOG_WITHDRAW = CommandSpec(
    name="profiles.catalog.withdraw",
    version=1,
    module="shared.profiles",
    title={"pl": "Wycofaj wizytówkę z katalogu", "en": "Take the card out of the directory"},
    summary={
        "pl": "Wizytówka znika z publicznego katalogu firm; sama zostaje.",
        "en": "The card leaves the public company directory; the card itself stays.",
    },
    model_description=(
        "Takes the company's card out of the public company directory. The card itself "
        "stays and can be published again. Does nothing when the card is not listed."
    ),
    input_schema=_NO_INPUT,
    output_schema=_CATALOG_OUTPUT,
    permission=PROFILES_MANAGE,
    risk="publish",
    run=_withdraw,
    undo="command:profiles.catalog.publish@1",
    preview=_withdraw_preview,
    no_version_reason="Withdrawal removes the listing; it changes none of the card's fields.",
)


_CATALOG_OPTIONS = {
    "type": "object",
    "x-data-class": "public",
    "properties": {
        "categories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "label": {"type": "object"},
                    # Trades the label does not name: „hydraulik”, „fryzjer”.
                    "keywords": {"type": "object"},
                },
            },
        },
        "cities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "name": {"type": "string"},
                    "voivodeship": {"type": "string"},
                },
            },
        },
    },
}


def _catalog_options(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    """The catalogue's own dictionary, in its order, for this company's type."""
    return {
        "categories": [
            {
                "key": category.key,
                "label": dict(category.label),
                "keywords": {locale: list(words) for locale, words in category.keywords.items()},
            }
            for category in categories(_organization_type(call)).values()
        ],
        "cities": [
            {"slug": city.slug, "name": city.name, "voivodeship": city.voivodeship}
            for city in cities().values()
        ],
    }


CATALOG_OPTIONS_READ = CommandSpec(
    name="profiles.catalog_options.read",
    version=1,
    module="shared.profiles",
    title={
        "pl": "Odczytaj kategorie i miasta katalogu",
        "en": "Read the directory's categories and towns",
    },
    summary={
        "pl": "Kategorie katalogu firm z nazwami i słowami kluczowymi oraz miasta z nazwami.",
        "en": "The directory's categories with names and keywords, and its towns with names.",
    },
    model_description=(
        "Returns the public company directory's dictionary for this kind of company: "
        "every category with its key, its name in each language and the trades it is found "
        "by (keywords), and every town with its slug, name and region. Use it to match what "
        "the person says about their business and town to a category key and a town slug "
        "for the company card. Only these keys and slugs are accepted; a town outside the "
        "list cannot be set."
    ),
    input_schema=_NO_INPUT,
    output_schema=_CATALOG_OPTIONS,
    permission=PROFILES_MANAGE,
    risk="read",
    run=_catalog_options,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)


def register_profile_commands() -> None:
    for spec in (CARD_READ, CARD_UPDATE, CATALOG_PUBLISH, CATALOG_WITHDRAW, CATALOG_OPTIONS_READ):
        register_command(spec)
