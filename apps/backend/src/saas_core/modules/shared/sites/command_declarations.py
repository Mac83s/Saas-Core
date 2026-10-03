"""The assistant's commands for the company's site (ADR-076 §1, A1b-11).

Thin adapters over the services the panel's Site Studio calls. What they
write is a draft: a new page from a template, unpublished, or the text of a
language version, which a person accepts and publishes through the decision
doors (TL9c). Text the assistant writes is the model's text: the service marks
it as AI text from the acting context (ADR-071 pkt 17). A legal page is never
written here — it is the person's (ADR-035 §4).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rest_framework.exceptions import ValidationError

from saas_core.modules.core.organizations.api import CommandSpec, Effect, Preview, register_command

from .blueprints import OWNER_FACT, read_blueprint_catalog
from .language_versions import get_locale_body, save_locale_body
from .localization import first_segment_reserved
from .models import PageTranslation, Site, SitePurpose
from .page_templates import page_template_catalog
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED
from .services import (
    PERSON_ONLY_PAGE_TYPES,
    SiteNotFound,
    assert_person_required,
    create_page,
    import_page_template,
    save_page_translation,
)

SITE_FEATURE = frozenset({"assistant.site_generation.enabled"})


def _uuid(arguments: Mapping[str, Any], field: str) -> UUID:
    try:
        return UUID(str(arguments[field]))
    except ValueError:
        raise ValidationError({field: ["To nie jest identyfikator."]}, code="invalid") from None


def _site(call: Any, site_id: Any) -> Site:
    """The site named, or the company's first own site when none is named."""
    sites = Site.all_objects.filter(
        organization_id=call.context.organization_id, purpose=SitePurpose.CUSTOMER
    ).order_by("created_at")
    site = (
        sites.filter(pk=_uuid({"site_id": site_id}, "site_id")).first()
        if site_id is not None
        else sites.first()
    )
    if site is None:
        raise SiteNotFound
    return site


# sites.blueprint_catalog.read@1


def _catalog(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    site = _site(call, arguments["site_id"])
    catalog = read_blueprint_catalog(site_id=site.id)
    return {
        "site_id": str(site.id),
        "default_locale": site.default_locale,
        "sites": [
            {"id": str(item.id), "name": item.name, "default_locale": item.default_locale}
            for item in Site.all_objects.filter(
                organization_id=call.context.organization_id, purpose=SitePurpose.CUSTOMER
            ).order_by("created_at")
        ],
        "templates": catalog["templates"],
        "catalog_hash": catalog["catalog_hash"],
    }


# sites.page_draft.from_template@1


def _template(arguments: Mapping[str, Any], site: Site) -> tuple[Any, dict[str, Any], str]:
    catalog = read_blueprint_catalog(site_id=site.id)
    offered = {item["id"]: item for item in catalog["templates"]}
    entry = offered.get(arguments["template_id"])
    if entry is None:
        raise ValidationError(
            {"template_id": ["Nie ma takiego szablonu dla tej strony."]}, code="invalid"
        )
    template = page_template_catalog().get(template_id=entry["id"], version=entry["version"])
    return template, entry, catalog["catalog_hash"]


def _slot_values(arguments: Mapping[str, Any], entry: dict[str, Any]) -> dict[str, str]:
    """Every slot: what the assistant wrote, or the template's own text."""
    slots = {slot["key"]: slot for slot in entry["slots"]}
    problems: dict[str, Any] = {}
    written: dict[str, str] = {}
    for index, item in enumerate(arguments["slots"]):
        slot = slots.get(item["key"])
        text = item["text"]
        if slot is None:
            problems[str(index)] = {"key": ["Szablon nie ma takiego miejsca na tekst."]}
        elif not text.strip() or "<" in text or ">" in text or OWNER_FACT.search(text):
            problems[str(index)] = {"text": ["Wpisz zwykły tekst, bez znaczników."]}
        elif len(text) > slot["max_length"]:
            problems[str(index)] = {
                "text": [f"Najwyżej {slot['max_length']} znaków w tym miejscu."]
            }
        else:
            written[item["key"]] = text
    if problems:
        raise ValidationError({"slots": problems})
    return {key: written.get(key, slot["default"]) for key, slot in slots.items()}


def _page_key(arguments: Mapping[str, Any], site: Site) -> str:
    key = str(arguments["key"]).strip().lower()
    if first_segment_reserved(key):
        raise ValidationError({"key": ["Ten adres jest zarezerwowany."]}, code="slug_reserved")
    if PageTranslation.all_objects.filter(
        organization_id=site.organization_id, site=site, slug=key
    ).exists():
        raise ValidationError({"key": ["Strona ma już podstronę pod tym adresem."]}, code="unique")
    return key


def _preview_draft(arguments: Mapping[str, Any], call: Any) -> Preview:
    site = _site(call, arguments["site_id"])
    template, entry, catalog_hash = _template(arguments, site)
    _slot_values(arguments, entry)
    key = _page_key(arguments, site)
    label = entry["labels"].get("pl") or template.id
    label_en = entry["labels"].get("en") or label
    name = arguments["name"]
    return Preview(
        effects=(
            Effect(
                kind="created",
                resource="sites.page",
                resource_id="",
                summary={
                    "pl": f"Nowa podstrona „{name}” (/{key}) z szablonu „{label}” — szkic, "
                    "nieopublikowany",
                    "en": f"New page “{name}” (/{key}) from the “{label_en}” template — a "
                    "draft, not published",
                },
            ),
        ),
        # The template catalogue the person saw: another version would draft
        # another page.
        observed_versions={f"sites.blueprint_catalog:{site.id}": catalog_hash},
    )


def _draft(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    site = _site(call, arguments["site_id"])
    template, entry, _catalog_hash = _template(arguments, site)
    values = _slot_values(arguments, entry)
    key = _page_key(arguments, site)
    page = create_page(
        site_id=site.id,
        name=arguments["name"],
        key=key,
        idempotency_key=f"{call.idempotency_key}-page",
    ).value
    version = import_page_template(
        page_id=page.id,
        template_id=template.id,
        template_version=template.version,
        expected_version=0,
        idempotency_key=f"{call.idempotency_key}-template",
        text_values=values,
        locale=site.default_locale,
    ).value
    save_page_translation(
        page_id=page.id,
        locale=site.default_locale,
        expected_version=0,
        slug=key,
        title=arguments["name"],
        description="",
        social_title="",
        social_description="",
        # The site's own language falls back to nothing: it is the source.
        allow_title_fallback=False,
        allow_description_fallback=False,
        allow_social_title_fallback=False,
        allow_social_description_fallback=False,
        idempotency_key=f"{call.idempotency_key}-translation",
    )
    return {
        "page_id": str(page.id),
        "site_id": str(site.id),
        "key": key,
        "draft_version": version.number,
        "published": False,
    }


# sites.locale_body.read@1 and .save@1


def _body(arguments: Mapping[str, Any]) -> Any:
    return get_locale_body(page_id=_uuid(arguments, "page_id"), locale=arguments["locale"])


def _read_body(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    body = _body(arguments)
    shown = [
        state
        for state in body.units
        if state.unit.data_class == "public" and not state.unit.placeholder
    ]
    return {
        "page_id": str(body.page.id),
        "locale": body.translation.locale,
        "body_version": body.translation.body_version,
        "units": [
            {
                "key": state.unit.key,
                "source": state.unit.text,
                "text": state.text,
                "max_length": state.unit.max_length,
            }
            for state in shown
        ],
        # A person's details and the owner's own facts never reach a model.
        "withheld_units": len(body.units) - len(shown),
    }


def _units(arguments: Mapping[str, Any]) -> dict[str, str]:
    return {item["key"]: item["text"] for item in arguments["units"]}


def _resource(body: Any) -> str:
    return f"sites.locale_body:{body.page.id}:{body.translation.locale}"


def _preview_save(arguments: Mapping[str, Any], call: Any) -> Preview:
    body = _body(arguments)
    if body.page.page_type in PERSON_ONLY_PAGE_TYPES:
        # A legal page is the person's to write, in any language.
        assert_person_required(call.context, "Strona prawna")
    save_locale_body(
        page_id=body.page.id,
        locale=body.translation.locale,
        source_version_id=body.source_version.id,
        expected_body_version=body.translation.body_version,
        units=_units(arguments),
        idempotency_key="",
        preview=True,
    )
    count = len(arguments["units"])
    return Preview(
        effects=(
            Effect(
                kind="updated",
                resource="sites.locale_body",
                resource_id=f"{body.page.id}:{body.translation.locale}",
                summary={
                    "pl": f"„{body.page.name}” po {body.translation.locale}: {count} fragmentów "
                    "tekstu AI — szkic do Twojej akceptacji",
                    "en": f"“{body.page.name}” in {body.translation.locale}: {count} pieces of "
                    "AI text — a draft for you to accept",
                },
            ),
        ),
        observed_versions={
            _resource(body): body.translation.body_version,
            f"sites.page_source:{body.page.id}": str(body.source_version.id),
        },
    )


def _save(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    body = _body(arguments)
    expected = call.preview.observed_versions[_resource(body)]
    saved = save_locale_body(
        page_id=body.page.id,
        locale=body.translation.locale,
        source_version_id=UUID(call.preview.observed_versions[f"sites.page_source:{body.page.id}"]),
        expected_body_version=expected,
        units=_units(arguments),
        idempotency_key=call.idempotency_key,
    ).value
    return {
        "page_id": str(saved.page.id),
        "locale": saved.translation.locale,
        "body_version": saved.translation.body_version,
        "published": False,
    }


_SITE_ID = {
    "type": ["string", "null"],
    "description": "The site; null for the company's first site.",
}
_PAGE_LOCALE = {
    "page_id": {"type": "string", "description": "The page (from the site's pages)."},
    "locale": {"type": "string", "description": "The language version, a two-letter code."},
}

CATALOG_READ = CommandSpec(
    name="sites.blueprint_catalog.read",
    version=1,
    module="shared.sites",
    title={"pl": "Odczytaj szablony podstron", "en": "Read page templates"},
    summary={
        "pl": "Szablony, z których można założyć podstronę, z miejscami na tekst.",
        "en": "The templates a page can start from, with their places for text.",
    },
    model_description=(
        "Returns the company's sites and the page templates its plan allows, each with the "
        "places for plain text (slot key, maximum length, the template's own text). Use it "
        "before drafting a page from a template."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["site_id"],
        "properties": {"site_id": _SITE_ID},
    },
    output_schema={
        "type": "object",
        "x-data-class": "public",
        "properties": {
            "site_id": {"type": "string"},
            "default_locale": {"type": "string"},
            "sites": {"type": "array"},
            "templates": {"type": "array"},
            "catalog_hash": {"type": "string"},
        },
    },
    permission=SITE_CONTENT_EDIT,
    entitlement=SITES_ENABLED,
    risk="read",
    run=_catalog,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)

PAGE_DRAFT = CommandSpec(
    name="sites.page_draft.from_template",
    version=1,
    module="shared.sites",
    title={"pl": "Szkic podstrony z szablonu", "en": "Draft a page from a template"},
    summary={
        "pl": "Nowa, nieopublikowana podstrona z szablonu i tekstem w jego miejscach.",
        "en": "A new, unpublished page from a template, with text in its places.",
    },
    model_description=(
        "Creates a new page on the site from a template, as an unpublished draft: its name, "
        "its address (key, lower-case letters, digits and hyphens) and plain text for the "
        "template's slots. A slot not given keeps the template's own text. Prices, quotes "
        "and the owner's own facts are never written. Use sites.blueprint_catalog.read first."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["site_id", "template_id", "name", "key", "slots"],
        "properties": {
            "site_id": _SITE_ID,
            "template_id": {"type": "string", "description": "The template's id."},
            "name": {"type": "string", "description": "The page's name, up to 160 characters."},
            "key": {"type": "string", "description": "The page's address after the domain."},
            "slots": {
                "type": "array",
                "description": "Text for the template's slots; others keep the template's.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["key", "text"],
                    "properties": {
                        "key": {"type": "string", "description": "The slot's key."},
                        "text": {"type": "string", "description": "Plain text for it."},
                    },
                },
            },
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": "public",
        "properties": {
            "page_id": {"type": "string"},
            "site_id": {"type": "string"},
            "key": {"type": "string"},
            "draft_version": {"type": "integer"},
            "published": {"type": "boolean"},
        },
    },
    permission=SITE_CONTENT_EDIT,
    entitlement=SITES_ENABLED,
    extra_features=SITE_FEATURE,
    risk="draft",
    run=_draft,
    undo="none:a draft page is deleted by the person in Site Studio",
    preview=_preview_draft,
    no_version_reason="A new page has no version yet.",
)

BODY_READ = CommandSpec(
    name="sites.locale_body.read",
    version=1,
    module="shared.sites",
    title={"pl": "Odczytaj wersję językową podstrony", "en": "Read a page's language version"},
    summary={
        "pl": "Fragmenty tekstu podstrony w źródle i w danym języku.",
        "en": "A page's pieces of text in its source and in one language.",
    },
    model_description=(
        "Returns one language version of a page: every piece of text (unit key, source "
        "text, current text in that language, maximum length) and the version. Pieces with "
        "a person's details or the owner's own facts are left out and counted. Use it before "
        "writing the language version."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["page_id", "locale"],
        "properties": _PAGE_LOCALE,
    },
    output_schema={
        "type": "object",
        "x-data-class": "public",
        "properties": {
            "page_id": {"type": "string"},
            "locale": {"type": "string"},
            "body_version": {"type": "integer"},
            "units": {"type": "array"},
            "withheld_units": {"type": "integer"},
        },
    },
    permission=SITE_CONTENT_EDIT,
    entitlement=SITES_ENABLED,
    risk="read",
    run=_read_body,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)

BODY_SAVE = CommandSpec(
    name="sites.locale_body.save",
    version=1,
    module="shared.sites",
    title={"pl": "Zapisz tekst wersji językowej", "en": "Write a language version's text"},
    summary={
        "pl": "Tekst AI w wersji językowej podstrony, do akceptacji przez osobę.",
        "en": "AI text in a page's language version, for a person to accept.",
    },
    model_description=(
        "Writes text into one language version of a page, piece by piece (unit key and "
        "text from sites.locale_body.read); pieces not given keep their text. The text is "
        "marked as AI text and stays a draft until the person accepts and publishes it. "
        "Legal pages are never written here."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["page_id", "locale", "units"],
        "properties": {
            **_PAGE_LOCALE,
            "units": {
                "type": "array",
                "description": "The pieces to write.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["key", "text"],
                    "properties": {
                        "key": {"type": "string", "description": "The unit's key."},
                        "text": {"type": "string", "description": "Its text in this language."},
                    },
                },
            },
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": "public",
        "properties": {
            "page_id": {"type": "string"},
            "locale": {"type": "string"},
            "body_version": {"type": "integer"},
            "published": {"type": "boolean"},
        },
    },
    permission=SITE_CONTENT_EDIT,
    entitlement=SITES_ENABLED,
    extra_features=SITE_FEATURE,
    risk="draft",
    run=_save,
    undo="restore_version",
    preview=_preview_save,
    version_field="expected_body_version",
)


def register_site_commands() -> None:
    for spec in (CATALOG_READ, PAGE_DRAFT, BODY_READ, BODY_SAVE):
        register_command(spec)
