"""Booking items in the company's other languages (ADR-069; plan TL12b).

Services, places, units, groups of units and teams keep their own text in
the company's first language; each other language is an `ItemTranslation`
row with the text and provenance by field. A person writes it through a setup
write (receipt, version, preview — ADR-072 §11); the public form reads names
in the visitor's language and falls back to the item's own.

A new kind of item (price lists, extras — later phases) registers itself with
`register_translatable`, and gets the same API and, from TL12c, the same
translation source. A team's name is a proper name: a person may translate
it, a model never gets it unless the company asks (its unit is a `name`).
Nothing here needs the translation engine; without it the rows are only what
people wrote.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import models, transaction
from rest_framework.exceptions import ErrorDetail, NotFound, ValidationError

from saas_core.content_protocol.provenance import ORIGIN_COPY, ORIGIN_HUMAN, Provenance, unit_hash
from saas_core.content_protocol.units import (
    DATA_PUBLIC,
    UNIT_NAME,
    UNIT_TEXT,
    Target,
    Unit,
)
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.locales import (
    assert_content_locale,
    organization_content_locales,
)
from saas_core.modules.core.organizations.models import Organization, OrganizationAuditAction
from saas_core.modules.shared.billing.decisions import FeatureOperation

from .models import (
    ItemTranslation,
    Location,
    LocationTranslation,
    ParticipantCategory,
    ParticipantCategoryTranslation,
    Resource,
    ResourceGroup,
    ResourceGroupTranslation,
    ResourceTranslation,
    Service,
    ServiceTranslation,
    StaffTeam,
    StaffTeamTranslation,
)
from .setup import Saved, _manage, check_version, setup_write

#: The source hash of a text written before provenance was kept.
LEGACY_SOURCE = "legacy"
LIMITS = {"name": 160, "description": 2000}


@dataclass(frozen=True, slots=True)
class Translatable:
    kind: str
    model: type[models.Model]
    translation: type[ItemTranslation]
    #: The translation's foreign key to the item.
    relation: str
    fields: tuple[str, ...]
    #: Its name is a proper name (a team): a `name` unit, never sent unasked.
    proper_name: bool = False


_KINDS: dict[str, Translatable] = {}


def register_translatable(item: Translatable) -> None:
    _KINDS[item.kind] = item


def translatables() -> tuple[Translatable, ...]:
    return tuple(_KINDS[kind] for kind in sorted(_KINDS))


def translatable(kind: str) -> Translatable:
    try:
        return _KINDS[kind]
    except KeyError:
        raise NotFound("Nie ma takiego rodzaju pozycji.") from None


for _builtin in (
    Translatable("service", Service, ServiceTranslation, "service", ("name",)),
    Translatable("location", Location, LocationTranslation, "location", ("name",)),
    Translatable("resource", Resource, ResourceTranslation, "resource", ("name", "description")),
    Translatable(
        "group", ResourceGroup, ResourceGroupTranslation, "group", ("name", "description")
    ),
    Translatable("team", StaffTeam, StaffTeamTranslation, "team", ("name",), proper_name=True),
    # Who comes: a quote's lines name it in the customer's language (ADR-072 §7).
    Translatable(
        "participant_category",
        ParticipantCategory,
        ParticipantCategoryTranslation,
        "category",
        ("name",),
    ),
):
    register_translatable(_builtin)


def source_locale(organization: Organization) -> str:
    """The language the company writes its items in: its first."""
    offered = organization_content_locales(organization)
    return offered[0] if offered else "pl"


def item_units(entry: Translatable, item: Any) -> tuple[Unit, ...]:
    units = []
    for field in entry.fields:
        text = str(getattr(item, field, "") or "")
        if not text.strip():
            continue
        units.append(
            Unit(
                key=field,
                kind=UNIT_NAME if entry.proper_name and field == "name" else UNIT_TEXT,
                text=text,
                data_class=DATA_PUBLIC,
                max_length=LIMITS.get(field),
            )
        )
    return tuple(units)


def translation_row(entry: Translatable, item: Any, locale: str) -> ItemTranslation | None:
    return entry.translation.all_objects.filter(
        organization_id=item.organization_id, locale=locale, **{entry.relation: item}
    ).first()


def row_targets(row: ItemTranslation | None, units: Iterable[Unit]) -> dict[str, Target]:
    texts = (row.texts if row is not None else None) or {}
    provenance = (row.provenance if row is not None else None) or {}
    targets: dict[str, Target] = {}
    for unit in units:
        text = texts.get(unit.key)
        if not text:
            continue
        stored = provenance.get(unit.key)
        targets[unit.key] = Target(
            str(text),
            Provenance.from_dict(stored)
            if stored
            else Provenance(origin=ORIGIN_HUMAN, source_hash=LEGACY_SOURCE),
        )
    return targets


def apply_item_translation(
    entry: Translatable,
    item: Any,
    locale: str,
    texts: Mapping[str, tuple[str, Provenance]],
    *,
    actor_id: UUID | None,
) -> tuple[ItemTranslation, dict[str, Any]]:
    """Writes fields of an item's language: the version moves, the history
    follows. Returns the row and what each field held before."""
    row = translation_row(entry, item, locale)
    if row is None:
        row = entry.translation(
            organization_id=item.organization_id, locale=locale, version=0, **{entry.relation: item}
        )
    before = row_targets(row, item_units(entry, item)) if row.pk else {}
    stored = dict(row.texts or {})
    provenance = dict(row.provenance or {})
    replaced: dict[str, Any] = {}
    for field, (text, origin) in texts.items():
        old = before.get(field)
        replaced[field] = (
            [old.text, old.provenance.as_dict() if old.provenance else {}]
            if old is not None
            else None
        )
        if text:
            stored[field] = text
            provenance[field] = origin.as_dict()
        else:
            stored.pop(field, None)
            provenance.pop(field, None)
    row.texts = stored
    row.provenance = provenance
    row.version += 1
    row.save()
    record_audit(
        organization=Organization.objects.get(pk=item.organization_id),
        action=OrganizationAuditAction.BOOKING_CATALOG_CHANGED,
        actor=User.objects.filter(pk=actor_id).first() if actor_id else None,
        target_type=f"{entry.kind}_translation",
        target_id=row.id,
        metadata={
            "item_id": str(item.id),
            "locale": locale,
            "version": row.version,
            "fields": sorted(texts),
            "origins": sorted({origin.origin for _text, origin in texts.values()}),
        },
    )
    return row, replaced


def _item(
    entry: Translatable, organization: Organization, item_id: UUID, *, lock: bool = False
) -> Any:
    rows = entry.model.all_objects.filter(organization=organization, pk=item_id)  # type: ignore[attr-defined]
    item = (rows.select_for_update() if lock else rows).first()
    if item is None:
        raise NotFound("Nie ma takiej pozycji.")
    return item


def list_item_translations(
    kind: str, item_id: UUID
) -> tuple[Translatable, Any, str, list[tuple[str, ItemTranslation | None]]]:
    """The item, its own language and each other language of the company."""
    entry = translatable(kind)
    _, organization = _manage(FeatureOperation.READ)
    item = _item(entry, organization, item_id)
    own = source_locale(organization)
    rows = {
        row.locale: row
        for row in entry.translation.all_objects.filter(
            organization=organization, **{entry.relation: item}
        )
    }
    locales = [code for code in organization_content_locales(organization) if code != own]
    locales += sorted(code for code in rows if code not in locales and code != own)
    return entry, item, own, [(code, rows.get(code)) for code in locales]


@transaction.atomic
def save_item_translation(
    *,
    kind: str,
    item_id: UUID,
    locale: str,
    texts: Mapping[str, str],
    expected_version: int | None,
    idempotency_key: str = "",
    preview: bool = False,
) -> Saved[ItemTranslation]:
    """A person's text of an item in another language, at the version they saw
    (0 for a language the item does not have yet)."""
    entry = translatable(kind)
    context, organization = _manage()
    return setup_write(
        context=context,
        action=f"{kind}.translation",
        target_id=item_id,
        request={"locale": locale, "texts": dict(texts), "expected_version": expected_version},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _write(
            context, organization, entry, item_id, locale, texts, expected_version
        ),
        replay=lambda row_id: _replayed(entry, organization, row_id),
    )


def _write(
    context: TenantContext,
    organization: Organization,
    entry: Translatable,
    item_id: UUID,
    locale: str,
    texts: Mapping[str, str],
    expected_version: int | None,
) -> Saved[ItemTranslation]:
    item = _item(entry, organization, item_id, lock=True)
    assert_content_locale(locale, organization=organization)
    if locale == source_locale(organization):
        raise ValidationError({
            "locale": [ErrorDetail("To język, w którym pozycja jest zapisana.", "locale_is_source")]
        })
    unknown = [field for field in texts if field not in entry.fields]
    if unknown:
        raise ValidationError({
            f"texts.{field}": [ErrorDetail("Ta pozycja nie ma takiego pola.", "unknown_field")]
            for field in unknown
        })
    too_long = [field for field, text in texts.items() if len(text) > LIMITS.get(field, 2000)]
    if too_long:
        raise ValidationError({
            f"texts.{field}": [ErrorDetail("Tekst jest za długi.", "max_length")]
            for field in too_long
        })
    current = translation_row(entry, item, locale)
    check_version(current.version if current is not None else 0, expected_version)
    units = {unit.key: unit for unit in item_units(entry, item)}
    written = {
        field: (
            text,
            Provenance(
                origin=ORIGIN_HUMAN,
                source_hash=units[field].source_hash if field in units else LEGACY_SOURCE,
                written_hash=unit_hash(UNIT_TEXT, text) if text else "",
            ),
        )
        for field, text in texts.items()
    }
    row, _replaced = apply_item_translation(entry, item, locale, written, actor_id=context.actor_id)
    return Saved(row, row.id, row.version, current is None)


def _replayed(
    entry: Translatable, organization: Organization, row_id: UUID
) -> Saved[ItemTranslation]:
    row = entry.translation.all_objects.get(organization=organization, pk=row_id)
    return Saved(row, row.id, row.version, False, replayed=True)


def localized_texts(
    entry: Translatable, items: Iterable[Any], locale: str | None
) -> dict[UUID, dict[str, str]]:
    """What a visitor reads in `locale`, by item and field: the translation, or
    the item's own text where there is none (a copied stand-in is none)."""
    listed = list(items)
    if not locale or not listed:
        return {}
    rows = entry.translation.all_objects.filter(
        organization_id=listed[0].organization_id,
        locale=locale,
        **{f"{entry.relation}__in": listed},
    )
    by_item = {getattr(row, f"{entry.relation}_id"): row for row in rows}
    found: dict[UUID, dict[str, str]] = {}
    for item in listed:
        row = by_item.get(item.id)
        if row is None:
            continue
        texts = {}
        for field in entry.fields:
            origin = (row.provenance or {}).get(field) or {}
            text = (row.texts or {}).get(field)
            if text and origin.get("origin") != ORIGIN_COPY:
                texts[field] = str(text)
        if texts:
            found[item.id] = texts
    return found


def customer_service_name(service: Service, locale: str) -> str:
    """The service's name in the customer's language when the company
    translated it, to freeze on a booking; empty when it is the company's."""
    name = (
        localized_texts(translatable("service"), [service], locale)
        .get(service.id, {})
        .get("name", "")
    )
    return name if name and name != service.name else ""
