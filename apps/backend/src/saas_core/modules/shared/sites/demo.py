"""Sites' part of the demo (core/organizations/demo.py): a company's site,
built the way its owner builds it in Site Studio and published.

For every organization whose scenario data has `sites` (the core's own
companies take theirs from `demo_data.py`) and that has no site yet: the site
at its subdomain of the platform, its pages — started from a page template
(„Noclegi”) and then filled in where the template says „[Uzupełnij: …]”, or
written block by block — each page's address, title and description in every
language of the company, the pages' texts in the other languages, and one
publication of the whole.

The other languages' texts come from the scenario, written by hand; no model
is called. They are saved through the language version's own door marked as
imported (`save_locale_body(imported=True)`): the panel says „Zaimportowane”,
not „Tłumaczenie AI” and not a person's correction. A page with a text the
scenario has no words for stays untranslated in that language and the language
is not published — the run says which text.

A company that already has a site keeps it untouched. The whole site is one
transaction: a refusal anywhere leaves no half-built site, and the next run
starts again.

Scenario data, under `sites`:

    {"site": {"name", "label"},
     "pages": [{"key", "name", "type", "template" | "blocks", "drop": [type],
                "fill": {template text: the company's text},
                "words": {text: {locale: text}},
                "meta": {locale: {"slug", "title", "description"}}}]}
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import APIException

from saas_core.modules.core.organizations.demo import site_address

from .block_decoration import stored_block_payload
from .language_versions import get_locale_body, save_locale_body, site_locales
from .localized_bodies import extract_units
from .models import Domain, Page, Site
from .page_templates import SEEDED_LOCALES, PageTemplate, page_template_catalog
from .services import (
    create_page,
    create_site,
    get_draft,
    import_page_template,
    list_sites,
    publish_site,
    save_draft,
    save_page_translation,
    set_page_type,
)

if TYPE_CHECKING:
    from saas_core.modules.core.organizations.demo import (
        DemoOrganization,
        DemoRun,
        DemoScenario,
    )


def _data(scenario: DemoScenario, spec: DemoOrganization) -> dict[str, Any] | None:
    from .demo_data import DEFAULTS  # noqa: PLC0415 — the core scenario's own companies

    data = spec.data.get("sites")
    if data is None and scenario.default:
        data = DEFAULTS.get(spec.key)
    return data


def describe(scenario: DemoScenario, spec: DemoOrganization) -> list[str]:
    data = _data(scenario, spec)
    if data is None:
        return []
    pages = ", ".join(
        f"{page['name']}" + (f" (szablon {page['template']})" if page.get("template") else "")
        for page in data["pages"]
    )
    return [
        f"strona {data['site']['label']}.<domena platformy>, opublikowana: {pages}; pozostałe "
        "języki firmy z tekstów scenariusza, oznaczone jako zaimportowane (bez modelu)"
    ]


def seed_sites(run: DemoRun) -> None:
    for spec in run.scenario.organizations:
        data = _data(run.scenario, spec)
        if data is None:
            continue
        try:
            with run.acting(spec.key):
                site = _site(run, spec, data)
                _link(run, spec.key, site)
        except (APIException, DjangoValidationError) as error:
            run.log(f"! strona {spec.name}: {getattr(error, 'detail', error)}")


def _site(run: DemoRun, spec: DemoOrganization, data: dict[str, Any]) -> Site:
    existing, _next = list_sites(cursor=None, limit=1)
    if existing:
        run.log(f"= strona {spec.name}: firma ma już stronę, zostaje bez zmian")
        return existing[0]
    label = data["site"]["label"]
    site = create_site(
        name=data["site"]["name"],
        slug=label,
        default_locale=run.organizations[spec.key].public_locales[0],
        subdomain_label=label,
        idempotency_key=str(run.stable_id("site", spec.slug)),
    ).value
    locales = site_locales(site)
    unpublished: dict[str, str] = {}
    for wanted in data["pages"]:
        page = create_page(
            site_id=site.id,
            name=wanted["name"],
            key=wanted["key"],
            idempotency_key=str(run.stable_id("page", spec.slug, wanted["key"])),
        ).value
        template = _write(run, spec, page, wanted)
        for locale in locales:
            meta = wanted["meta"].get(locale)
            if meta is None:
                unpublished.setdefault(locale, "strona nie ma adresu i tytułu w tym języku")
                continue
            save_page_translation(
                page_id=page.id,
                locale=locale,
                expected_version=0,
                slug=meta["slug"],
                title=meta["title"],
                description=meta["description"],
                social_title="",
                social_description="",
                allow_title_fallback=False,
                allow_description_fallback=False,
                allow_social_title_fallback=False,
                allow_social_description_fallback=False,
                idempotency_key=str(run.stable_id("meta", spec.slug, wanted["key"], locale)),
            )
        if wanted.get("type"):
            set_page_type(page_id=page.id, page_type=wanted["type"])
        for locale in locales[1:]:
            if locale not in wanted["meta"]:
                continue
            if missing := _words(run, spec, page, wanted, locale, template):
                unpublished.setdefault(locale, f"brak słów dla „{missing}”")
    publish_site(site_id=site.id, idempotency_key=str(run.stable_id("publish", spec.slug)))
    live = [locale for locale in locales if locale not in unpublished]
    run.log(f"+ strona {spec.name}: opublikowana, języki {', '.join(live)}")
    for locale, reason in unpublished.items():
        run.log(f"= strona {spec.name}: język {locale} nieopublikowany — {reason}")
    site.refresh_from_db()
    return site


def _write(
    run: DemoRun, spec: DemoOrganization, page: Page, wanted: dict[str, Any]
) -> PageTemplate | None:
    """The page's content in the site's own language: started from a template
    and filled in where it leaves the company's facts open, or its own blocks."""
    key = wanted["key"]
    template_id = wanted.get("template")
    if not template_id:
        save_draft(
            page_id=page.id,
            expected_version=page.version,
            blocks=[dict(block) for block in wanted["blocks"]],
            media_asset_ids=[],
            idempotency_key=str(run.stable_id("draft", spec.slug, key)),
        )
        return None
    versions = page_template_catalog().templates[template_id]
    template = versions[max(versions)]
    import_page_template(
        page_id=page.id,
        template_id=template.id,
        template_version=template.version,
        expected_version=page.version,
        idempotency_key=str(run.stable_id("template", spec.slug, key)),
    )
    draft = get_draft(page_id=page.id)
    dropped = set(wanted.get("drop", ()))
    blocks = [
        _filled(stored_block_payload(block), wanted.get("fill", {}))
        for block in draft.blocks
        if block.block_type not in dropped
    ]
    page.refresh_from_db()
    save_draft(
        page_id=page.id,
        expected_version=page.version,
        blocks=blocks,
        media_asset_ids=list(draft.media_asset_ids),
        idempotency_key=str(run.stable_id("fill", spec.slug, key)),
    )
    return template


def _filled(value: Any, fill: dict[str, str]) -> Any:
    """`value` with every text the company filled in put in its place."""
    if isinstance(value, dict):
        return {name: _filled(item, fill) for name, item in value.items()}
    if isinstance(value, list):
        return [_filled(item, fill) for item in value]
    if isinstance(value, str):
        return fill.get(value, value)
    return value


def _words(
    run: DemoRun,
    spec: DemoOrganization,
    page: Page,
    wanted: dict[str, Any],
    locale: str,
    template: PageTemplate | None,
) -> str:
    """Writes the page's texts in `locale` from the scenario's words — and,
    for a template's own texts, from the template's recipe in that language.
    Answers the first text there are no words for, or "" when all are there."""
    words: dict[str, dict[str, str]] = wanted.get("words", {})
    recipe: dict[str, str] = {}
    source = page.site.default_locale
    if template is not None and {locale, source} <= set(SEEDED_LOCALES):
        theirs = {unit.key: unit.text for unit in extract_units(template.draft_blocks(locale))}
        recipe = {
            unit.text: theirs[unit.key]
            for unit in extract_units(template.draft_blocks(source))
            if unit.key in theirs
        }
    body = get_locale_body(page_id=page.id, locale=locale)
    units: dict[str, str] = {}
    missing = ""
    for state in body.units:
        if state.unit.copied:
            continue
        text = words.get(state.unit.text, {}).get(locale) or recipe.get(state.unit.text)
        if text:
            units[state.unit.key] = text
        else:
            missing = missing or state.unit.text
    if units:
        save_locale_body(
            page_id=page.id,
            locale=locale,
            source_version_id=body.source_version.id,
            expected_body_version=body.translation.body_version,
            units=units,
            idempotency_key=str(run.stable_id("words", spec.slug, wanted["key"], locale)),
            imported=True,
        )
    return missing


def _link(run: DemoRun, key: str, site: Site) -> None:
    """Where the company's site answers, for the guide."""
    domain = (
        Domain.all_objects.filter(organization_id=site.organization_id, site=site)
        .order_by("-is_canonical", "created_at")
        .first()
    )
    if domain is not None and site.current_publication_id is not None:
        run.links[key]["site"] = site_address(domain.hostname)
