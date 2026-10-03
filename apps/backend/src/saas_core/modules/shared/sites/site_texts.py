"""Texts of the whole site in other languages (ADR-070 pkt 15; plan TL11c).

The tagline, the footer text and its link labels, the names of collections and
tags: one translation each per language, found by the hash of the source text
(`SiteTextTranslation`), so a reordered footer keeps its translations.

- **Units** are what the site shows now: the tagline and footer from the
  published appearance, collection names, and the names of tags a published
  article carries. A unit's key is where the text stands (`header/tagline`,
  `footer/link/<href hash>`, `collection/<id>`, `tag/<id>`), which is how a
  reworded text finds its old translation — it reads as stale.
- **Publications** carry, per language, the text visitors read for each key
  (`snapshot["site_texts"]`): a current translation, or a person's or an
  integration's one of a reworded text until they decide; anything else shows
  the source text, marked with its language.
- A person writes translations here (`save_site_texts`) and publishes them
  (`publish_site_texts`); a translation job writes through
  `site_text_source`.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from saas_core.content_protocol.provenance import (
    ORIGIN_AI,
    ORIGIN_HUMAN,
    Provenance,
    unit_hash,
)
from saas_core.content_protocol.units import DATA_PUBLIC, UNIT_TEXT, Target, Unit, unit_state
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .language_versions import site_locales
from .models import (
    ContentCollection,
    ContentEntryState,
    ContentTag,
    Publication,
    PublicationReason,
    Site,
    SiteTextTranslation,
    canonical_json_hash,
)
from .permissions import SITE_CONTENT_EDIT, SITE_PUBLISH, SITES_ENABLED
from .services import SiteNotFound, SitePublicationNotReady, _idempotency_key

KEY_TAGLINE = "header/tagline"
KEY_FOOTER = "footer/text"
LINK_PREFIX = "footer/link/"
SITE_TEXTS_SAVED = "sites.site_texts.saved"
SITE_TEXTS_PUBLISHED = "sites.site_texts.published"


class SiteTextsVersionConflict(APIException):
    status_code = 409
    default_detail = "Tłumaczenia tekstów witryny zmieniły się. Wczytaj aktualną wersję."
    default_code = "site_texts_version_conflict"


class SiteTextLocaleInvalid(APIException):
    status_code = 400
    default_detail = "Teksty witryny tłumaczy się na jej inne języki, nie na język źródłowy."
    default_code = "site_texts_locale_invalid"


@dataclass(frozen=True, slots=True)
class SiteText:
    key: str
    role: str
    text: str
    max_length: int


@dataclass(frozen=True, slots=True)
class SiteTextItem:
    key: str
    role: str
    source_text: str
    text: str
    origin: str
    state: str
    pending_text: str
    pending_reason: str


@dataclass(frozen=True, slots=True)
class SiteTexts:
    site: Site
    locale: str
    version: str
    items: tuple[SiteTextItem, ...]


# -- what the site says --------------------------------------------------------


def link_keys(links: Sequence[Mapping[str, Any]]) -> list[str]:
    """A footer link's key follows its address, not its place in the list."""
    keys: list[str] = []
    seen: dict[str, int] = {}
    for link in links:
        base = LINK_PREFIX + hashlib.sha256(str(link.get("href", "")).encode()).hexdigest()[:12]
        seen[base] = seen.get(base, 0) + 1
        keys.append(base if seen[base] == 1 else f"{base}~{seen[base]}")
    return keys


def appearance_texts(appearance: Mapping[str, Any] | None) -> list[SiteText]:
    if not isinstance(appearance, Mapping):
        return []
    header = appearance.get("header") or {}
    footer = appearance.get("footer") or {}
    texts: list[SiteText] = []
    tagline = str(header.get("tagline") or "").strip()
    if tagline:
        texts.append(SiteText(KEY_TAGLINE, "tagline", tagline, 180))
    text = str(footer.get("text") or "").strip()
    if text:
        texts.append(SiteText(KEY_FOOTER, "footer", text, 300))
    links = [link for link in footer.get("links") or [] if isinstance(link, Mapping)]
    for key, link in zip(link_keys(links), links, strict=True):
        label = str(link.get("label") or "").strip()
        if label:
            texts.append(SiteText(key, "footer_link", label, 80))
    return texts


def published_appearance(site: Site) -> dict[str, Any] | None:
    publication = site.current_publication
    if publication is None:
        return None
    appearance = publication.snapshot.get("appearance")
    return appearance if isinstance(appearance, dict) else None


def site_text_units(site: Site, appearance: Mapping[str, Any] | None) -> tuple[Unit, ...]:
    """Everything the site says outside its pages and articles, in order."""
    texts = appearance_texts(appearance)
    texts += [
        SiteText(f"collection/{collection.id}", "collection", collection.name.strip(), 160)
        for collection in ContentCollection.all_objects.filter(
            organization_id=site.organization_id, site_id=site.id
        ).order_by("key")
        if collection.name.strip()
    ]
    texts += [
        SiteText(f"tag/{tag.id}", "tag", tag.name.strip(), 120)
        for tag in ContentTag.all_objects.filter(
            organization_id=site.organization_id,
            site_id=site.id,
            entry_links__entry__state=ContentEntryState.PUBLISHED,
        )
        .distinct()
        .order_by("slug")
        if tag.name.strip()
    ]
    return tuple(
        Unit(
            key=text.key,
            kind=UNIT_TEXT,
            text=text.text,
            data_class=DATA_PUBLIC,
            max_length=text.max_length,
        )
        for text in texts
    )


def unit_role(key: str) -> str:
    if key == KEY_TAGLINE:
        return "tagline"
    if key == KEY_FOOTER:
        return "footer"
    if key.startswith(LINK_PREFIX):
        return "footer_link"
    return key.split("/", 1)[0]


def basis_token(units: Iterable[Unit]) -> str:
    return _token([[unit.key, unit.source_hash] for unit in units])


# -- what the language says ----------------------------------------------------


def translation_rows(site: Site, locale: str, *, lock: bool = False) -> list[SiteTextTranslation]:
    rows = SiteTextTranslation.all_objects.filter(
        organization_id=site.organization_id, site_id=site.id, locale=locale
    )
    if lock:
        rows = rows.select_for_update()
    return list(rows.order_by("updated_at", "id"))


def target_token(rows: Iterable[SiteTextTranslation]) -> str:
    """Changes with every write to the language's texts, accepted or waiting."""
    return _token(
        sorted([row.source_hash, row.text, row.pending_text, row.anchor] for row in rows)
    )


def targets(units: Iterable[Unit], rows: Sequence[SiteTextTranslation]) -> dict[str, Target]:
    """The translation of each unit: by the hash of its text, else — a text
    reworded in its place — the one last seen there, which reads as stale."""
    by_hash = {row.source_hash: row for row in rows if row.text.strip()}
    by_anchor = {row.anchor: row for row in rows if row.text.strip()}
    found: dict[str, Target] = {}
    for unit in units:
        row = by_hash.get(unit.source_hash) or by_anchor.get(unit.key)
        if row is not None:
            found[unit.key] = _target(row.text, row.provenance)
    return found


def shown_texts(units: Iterable[Unit], rows: Sequence[SiteTextTranslation]) -> dict[str, str]:
    """What visitors read in the language, per key: a current translation, or
    a person's or an integration's of a text reworded since — theirs until
    they decide. Without one, the source text shows (`localize_appearance`)."""
    units = tuple(units)
    found = targets(units, rows)
    shown: dict[str, str] = {}
    for unit in units:
        target = found.get(unit.key)
        if target is None:
            continue
        state = unit_state(unit, target)
        if state.status in ("fresh", "unverified") or (state.status == "stale" and state.protected):
            shown[unit.key] = target.text
    return shown


def snapshot_site_texts(site: Site, appearance: Mapping[str, Any] | None) -> dict[str, Any]:
    """`site_texts` for a whole-site publication: every language's current
    translations of what the publication shows."""
    units = site_text_units(site, appearance)
    if not units:
        return {}
    texts = {
        locale: shown
        for locale in site_locales(site)
        if locale != site.default_locale
        and (shown := shown_texts(units, translation_rows(site, locale)))
    }
    return texts


def localize_appearance(
    appearance: Mapping[str, Any] | None, shown: Mapping[str, str], source_locale: str
) -> tuple[Any, dict[str, str]]:
    """The appearance as a page in another language shows it — each text its
    translation — and the texts still in the source language, by path
    (`header.tagline`, `footer.text`, `footer.links.<i>.label`), so the page
    can mark them with that language. The appearance itself keeps its schema."""
    if not isinstance(appearance, Mapping):
        return appearance, {}
    localized = copy.deepcopy(dict(appearance))
    untranslated: dict[str, str] = {}

    def place(holder: dict[str, Any], field: str, path: str, key: str) -> None:
        if not str(holder.get(field) or "").strip():
            return
        if key in shown:
            holder[field] = shown[key]
        else:
            untranslated[path] = source_locale

    header = localized.get("header")
    if isinstance(header, dict):
        place(header, "tagline", "header.tagline", KEY_TAGLINE)
    footer = localized.get("footer")
    if isinstance(footer, dict):
        place(footer, "text", "footer.text", KEY_FOOTER)
        raw = footer.get("links") or []
        links = [link for link in raw if isinstance(link, dict)]
        for index, (key, link) in enumerate(zip(link_keys(links), links, strict=True)):
            place(link, "label", f"footer.links.{index}.label", key)
    return localized, untranslated


# -- a person's translations ---------------------------------------------------


def list_site_texts(*, site_id: UUID, locale: str) -> SiteTexts:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ)
    site = _site(context, site_id)
    _assert_locale(site, locale)
    return _texts(site, locale)


@transaction.atomic
def save_site_texts(
    *, site_id: UUID, locale: str, expected_version: str, texts: Mapping[str, str]
) -> SiteTexts:
    """A person's translations of the site's texts, by key; an empty one
    removes the translation. They go out with the next publication of the
    site or of these texts (`publish_site_texts`)."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    site = _site(context, site_id, lock=True)
    _assert_locale(site, locale)
    units = {unit.key: unit for unit in site_text_units(site, published_appearance(site))}
    rows = translation_rows(site, locale, lock=True)
    if target_token(rows) != expected_version:
        raise SiteTextsVersionConflict
    errors = {
        f"texts.{key}": ["Witryna nie pokazuje takiego tekstu."]
        for key in texts
        if key not in units
    }
    for key, text in texts.items():
        limit = units[key].max_length if key in units else None
        if limit is not None and len(text.strip()) > limit:
            errors[f"texts.{key}"] = [f"Najwyżej {limit} znaków."]
    if errors:
        raise ValidationError(errors)
    origin = ORIGIN_AI if context.acting_via else ORIGIN_HUMAN
    at = timezone.now().isoformat()
    for key, raw in texts.items():
        unit, text = units[key], raw.strip()
        row = store_row(site, locale, unit)
        row.text = text
        row.provenance = (
            Provenance(
                origin=origin,
                source_hash=unit.source_hash,
                written_hash=unit_hash(unit.kind, text),
                model="",
                at=at,
            ).as_dict()
            if text
            else None
        )
        row.origin_ref = context.acting_ref or ""
        row.save()
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=SITE_TEXTS_SAVED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="site",
        target_id=site.id,
        metadata={"locale": locale, "keys": sorted(texts)},
    )
    return _texts(site, locale)


@transaction.atomic
def publish_site_texts(*, site_id: UUID, locale: str, idempotency_key: str) -> Publication:
    """The language's site texts go out now, in a derived publication of
    what is already public — nobody's drafts go with them."""
    from .language_decisions import _person

    context = _person(SITE_PUBLISH)
    key = _idempotency_key(idempotency_key)
    site = _site(context, site_id, lock=True)
    _assert_locale(site, locale)
    if site.current_publication is None:
        raise SitePublicationNotReady
    publication = republish_site_texts(
        context,
        site,
        locale,
        reason=PublicationReason.LOCALE_PUBLISH,
        idempotency_key=f"texts:{key}",
    )
    if publication is None:
        # Visitors already read these texts as they are.
        return site.current_publication
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=SITE_TEXTS_PUBLISHED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="site",
        target_id=site.id,
        metadata={"locale": locale, "publication_id": str(publication.id)},
    )
    return publication


def republish_site_texts(
    context: Any,
    site: Site,
    locale: str,
    *,
    reason: str,
    idempotency_key: str,
    keys: Iterable[str] | None = None,
) -> Publication | None:
    """A derived publication with the language's site texts as they are now:
    all of them, or only `keys` (what one job wrote), the rest as published."""
    from .language_decisions import _current_snapshot, _publish

    if site.current_publication is None:
        return None
    snapshot = _current_snapshot(site)
    units = site_text_units(site, snapshot.get("appearance"))
    shown = shown_texts(units, translation_rows(site, locale))
    texts = {**(snapshot.get("site_texts") or {})}
    language = dict(texts.get(locale) or {})
    if keys is None:
        language = shown
    else:
        for key in keys:
            if key in shown:
                language[key] = shown[key]
            else:
                language.pop(key, None)
    if language:
        texts[locale] = language
    else:
        texts.pop(locale, None)
    if texts == (snapshot.get("site_texts") or {}):
        return None
    snapshot["site_texts"] = texts
    scope = f"texts:{canonical_json_hash([idempotency_key, locale])[:40]}"
    publication: Publication = _publish(context, site, snapshot, scope, reason, scope)
    return publication


def store_row(site: Site, locale: str, unit: Unit) -> SiteTextTranslation:
    row, _created = SiteTextTranslation.all_objects.get_or_create(
        organization_id=site.organization_id,
        site=site,
        locale=locale,
        source_hash=unit.source_hash,
        defaults={"source_text": unit.text, "anchor": unit.key},
    )
    if row.anchor != unit.key:
        row.anchor = unit.key
    return row


def _texts(site: Site, locale: str) -> SiteTexts:
    units = site_text_units(site, published_appearance(site))
    rows = translation_rows(site, locale)
    found = targets(units, rows)
    pending = {row.source_hash: row for row in rows if row.pending_text}
    items = []
    for unit in units:
        target = found.get(unit.key)
        waiting = pending.get(unit.source_hash)
        items.append(
            SiteTextItem(
                key=unit.key,
                role=unit_role(unit.key),
                source_text=unit.text,
                text=target.text if target is not None else "",
                origin=(
                    target.provenance.origin
                    if target is not None and target.provenance is not None
                    else ""
                ),
                state=unit_state(unit, target).status,
                pending_text=waiting.pending_text if waiting is not None else "",
                pending_reason=waiting.pending_reason if waiting is not None else "",
            )
        )
    return SiteTexts(site=site, locale=locale, version=target_token(rows), items=tuple(items))


def _site(context: Any, site_id: UUID, *, lock: bool = False) -> Site:
    sites = Site.all_objects.select_related("current_publication", "organization")
    if lock:
        sites = sites.select_for_update(of=("self",))
    site = sites.filter(pk=site_id, organization_id=context.organization_id).first()
    if site is None:
        raise SiteNotFound
    return site


def _assert_locale(site: Site, locale: str) -> None:
    if locale == site.default_locale or locale not in site_locales(site):
        raise SiteTextLocaleInvalid


def _target(text: str, provenance: Any) -> Target:
    return Target(
        text=text,
        provenance=Provenance.from_dict(provenance) if isinstance(provenance, dict) else None,
    )


def _token(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()[:16]


__all__ = [
    "KEY_FOOTER",
    "KEY_TAGLINE",
    "SiteTexts",
    "appearance_texts",
    "link_keys",
    "list_site_texts",
    "localize_appearance",
    "publish_site_texts",
    "republish_site_texts",
    "save_site_texts",
    "site_text_units",
    "snapshot_site_texts",
]
