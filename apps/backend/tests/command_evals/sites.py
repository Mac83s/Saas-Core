"""Evals of the site commands (`shared/sites/command_declarations.py`)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest import mock

from django.db.models import F

from saas_core.modules.core.organizations.context import TenantContext, activate_tenant_context
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)
from saas_core.modules.shared.sites.language_versions import get_locale_body
from saas_core.modules.shared.sites.models import Page, PageTranslation, Site
from saas_core.modules.shared.sites.services import (
    create_page,
    create_site,
    save_draft,
    save_page_translation,
)

from . import CommandEval

HERO = {"block_type": "core.hero", "schema_version": 6, "data": {"title": "Witaj", "text": "Domki"}}


def _site(context: TenantContext) -> None:
    """Sites in the plan, a site with a page and its English version."""
    Organization.objects.filter(pk=context.organization_id).update(public_locales=["pl", "en"])
    EntitlementSnapshot.all_objects.create(
        organization_id=context.organization_id,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        # A template's photos go to the company's storage.
        features={"sites.enabled": True, "storage.enabled": True},
        quotas={"sites.max": 3, "storage.bytes": 50_000_000},
        sources={
            "sites.enabled": {"kind": "plan"},
            "storage.enabled": {"kind": "plan"},
            "sites.max": {"kind": "plan"},
            "storage.bytes": {"kind": "plan"},
        },
    )
    with activate_tenant_context(context):
        site = create_site(
            name="Domki",
            slug=f"domki-{str(context.organization_id)[-6:]}",
            default_locale="pl",
            idempotency_key="eval-site",
        ).value
        page = create_page(site_id=site.id, name="Start", key="start", idempotency_key="p").value
        save_draft(
            page_id=page.id,
            expected_version=0,
            blocks=[HERO],
            media_asset_ids=[],
            idempotency_key="d",
        )
        for locale, slug in (("pl", "start"), ("en", "home")):
            save_page_translation(
                page_id=page.id,
                locale=locale,
                expected_version=0,
                slug=slug,
                title=slug.title(),
                description="Opis",
                social_title="",
                social_description="",
                allow_title_fallback=locale != "pl",
                allow_description_fallback=locale != "pl",
                allow_social_title_fallback=locale != "pl",
                allow_social_description_fallback=locale != "pl",
                idempotency_key=f"t-{locale}",
            )


def _page(context: TenantContext) -> Page:
    return Page.all_objects.filter(organization_id=context.organization_id).first()


def _state(context: TenantContext) -> dict[str, Any]:
    organization_id = context.organization_id
    return {
        "pages": sorted(
            Page.all_objects.filter(organization_id=organization_id).values_list("key", "version")
        ),
        "bodies": sorted(
            PageTranslation.all_objects.filter(organization_id=organization_id).values_list(
                "locale", "body_version"
            )
        ),
        "sites": Site.all_objects.filter(organization_id=organization_id).count(),
    }


def _english(context: TenantContext, text: str, key: str = "") -> dict[str, Any]:
    page = _page(context)
    if not key:
        with activate_tenant_context(context):
            key = get_locale_body(page_id=page.id, locale="en").units[0].unit.key
    return {"page_id": str(page.id), "locale": "en", "units": [{"key": key, "text": text}]}


def _template_draft(context: TenantContext, **given: Any) -> dict[str, Any]:
    from saas_core.modules.shared.sites.blueprints import read_blueprint_catalog  # noqa: PLC0415

    site = Site.all_objects.get(organization_id=context.organization_id)
    with activate_tenant_context(context):
        template = read_blueprint_catalog(site_id=site.id)["templates"][0]
    return {
        "site_id": None,
        "template_id": template["id"],
        "name": "Oferta",
        "key": "oferta",
        "slots": [{"key": template["slots"][0]["key"], "text": "Domki nad jeziorem"}],
        **given,
    }


@contextmanager
def _memory_storage() -> Iterator[None]:
    """A template's photos are copied into the company's storage: in memory here."""
    from test_sites_api import CleanTemplateMediaScanner, TemplateMediaStorage  # noqa: PLC0415

    storage, scanner = TemplateMediaStorage(), CleanTemplateMediaScanner()
    with (
        mock.patch("saas_core.modules.shared.media.services.get_object_storage", lambda: storage),
        mock.patch("saas_core.modules.shared.media.services.get_malware_scanner", lambda: scanner),
    ):
        yield


def _bump(context: TenantContext) -> None:
    PageTranslation.all_objects.filter(organization_id=context.organization_id, locale="en").update(
        body_version=F("body_version") + 1
    )


EVALS = {
    "sites.blueprint_catalog.read@1": CommandEval(
        arguments=lambda _context: {"site_id": None},
        wrong_arguments={"site_id": None, "template_id": "x"},
        wrong_field="template_id",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_state,
        prepare=_site,
    ),
    "sites.page_draft.from_template@1": CommandEval(
        arguments=_template_draft,
        # Refused by the adapter: a template slot takes plain text only.
        wrong_arguments=lambda context: _template_draft(
            context,
            slots=[{"key": _template_draft(context)["slots"][0]["key"], "text": "<b>Domki</b>"}],
        ),
        wrong_field="slots.0.text",
        stale="nie dotyczy: nowa podstrona nie ma jeszcze wersji",
        state=_state,
        prepare=_site,
        around=_memory_storage,
    ),
    "sites.locale_body.read@1": CommandEval(
        arguments=lambda context: {"page_id": str(_page(context).id), "locale": "en"},
        wrong_arguments={"page_id": "x", "locale": "en", "units": []},
        wrong_field="units",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_state,
        prepare=_site,
    ),
    "sites.seo_preview.read@1": CommandEval(
        arguments=lambda context: {
            "site_id": None,
            "page_id": str(_page(context).id),
            "locale": "pl",
        },
        wrong_arguments=lambda context: {
            "site_id": None,
            "page_id": str(_page(context).id),
            "locale": "pl",
            "publish": True,
        },
        wrong_field="publish",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_state,
        prepare=_site,
    ),
    "sites.locale_body.save@1": CommandEval(
        arguments=lambda context: _english(context, "Welcome"),
        # Refused by the service: the unit does not exist on the page.
        wrong_arguments=lambda context: _english(context, "Welcome", key="9/title"),
        wrong_field="units.9/title",
        stale=_bump,
        state=_state,
        prepare=_site,
    ),
}
