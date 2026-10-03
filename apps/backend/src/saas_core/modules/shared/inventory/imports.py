"""The catalogue from a CSV file (warehouse plan phase 10c).

A company moving in brings its items — and what lies on the shelf — as one
file from a spreadsheet. The same service previews and saves: the preview
parses, matches and validates every row and writes nothing; the save does the
same and then writes everything or nothing. Items are matched by SKU, then by
name; a row with a quantity also receives that much as opening stock, all rows
in one PW into one warehouse.

The file is read, never kept: the history records the counts and a hash of the
text. A cell that starts like a spreadsheet formula (`=`, `+`, `-`, `@`) is
text here like any other and is never evaluated; the preview flags it, so the
person sees it before it lands in the catalogue. The limits on rows and size
are protective, not business rules.
"""

from __future__ import annotations

import csv
import hashlib
import io
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from django.db import transaction
from django.http import HttpRequest
from django.utils.text import slugify
from rest_framework.exceptions import APIException, ErrorDetail, ValidationError

from saas_core.modules.core.organizations.models import (
    OrganizationAuditAction,
    OrganizationAuditEntry,
)

from .models import (
    DocumentKind,
    InventoryCategory,
    InventoryItem,
    ItemUnit,
    LocationKind,
    StockLocation,
    VatRate,
)
from .services import (
    LineInput,
    _audit,
    _get,
    _manage_context,
    _organization,
    _post,
    _write_lines,
    default_warehouse,
    organization_today,
)

#: Protective limits of one import (ADR-078 pkt 16: not business rules).
MAX_IMPORT_ROWS = 2000
MAX_IMPORT_BYTES = 1_000_000
DELIMITERS = (";", ",", "\t")
#: What a spreadsheet would run as a formula if the text were exported back.
FORMULA_START = ("=", "+", "-", "@")
#: How many rows of problems one refusal names.
REPORTED_ERRORS = 50
IMPORT_NAMESPACE = uuid.UUID("5d3c1a2e-7b64-4f0f-9d0a-1c9e5a4b7f10")


@dataclass(frozen=True, slots=True)
class Column:
    key: str
    headers: tuple[str, ...]
    label: Mapping[str, str]
    description: Mapping[str, str]
    example: str
    required: bool = False


COLUMNS: tuple[Column, ...] = (
    Column(
        "name",
        ("nazwa", "name"),
        {"pl": "Nazwa", "en": "Name"},
        {"pl": "Nazwa pozycji, jedyna w katalogu.", "en": "The item's name, unique."},
        "Rękawiczki nitrylowe M",
        required=True,
    ),
    Column(
        "sku",
        ("sku", "kod", "symbol"),
        {"pl": "SKU", "en": "SKU"},
        {
            "pl": "Własny kod pozycji; po nim import rozpoznaje pozycję, która już jest.",
            "en": "Your own code; an existing item is recognised by it.",
        },
        "REK-M",
    ),
    Column(
        "ean",
        ("ean", "kod kreskowy", "barcode"),
        {"pl": "EAN", "en": "EAN"},
        {"pl": "Kod kreskowy, do 14 cyfr.", "en": "The barcode, up to 14 digits."},
        "5901234123457",
    ),
    Column(
        "category",
        ("kategoria", "category"),
        {"pl": "Kategoria", "en": "Category"},
        {
            "pl": "Nazwa kategorii; nieznaną import założy.",
            "en": "The category's name; an unknown one is created.",
        },
        "Materiał",
    ),
    Column(
        "unit",
        ("jednostka", "jm", "j.m.", "unit"),
        {"pl": "Jednostka", "en": "Unit"},
        {
            "pl": "szt., opak., ml, l, g, kg, m albo godz.; puste — szt.",
            "en": "piece, pack, ml, l, g, kg, m or hour; empty — piece.",
        },
        "opak.",
    ),
    Column(
        "minimum_quantity",
        ("stan minimalny", "minimum", "min"),
        {"pl": "Stan minimalny", "en": "Minimum"},
        {"pl": "Minimum w magazynie; 0 — bez.", "en": "The warehouse minimum; 0 — none."},
        "5",
    ),
    Column(
        "sale_price",
        ("cena sprzedaży netto", "cena sprzedaży", "cena sprzedazy", "sale price"),
        {"pl": "Cena sprzedaży netto", "en": "Sale price, net"},
        {"pl": "W walucie firmy, np. 12,50.", "en": "In the company's currency, e.g. 12.50."},
        "39,00",
    ),
    Column(
        "vat_rate",
        ("vat", "stawka vat"),
        {"pl": "VAT", "en": "VAT"},
        {"pl": "23, 8, 5, 0 albo zw; puste — 23.", "en": "23, 8, 5, 0 or zw; empty — 23."},
        "23",
    ),
    Column(
        "tracks_lots",
        ("partie", "lots"),
        {"pl": "Partie", "en": "Lots"},
        {
            "pl": "tak — pozycja z partiami i datami ważności.",
            "en": "yes — the item is kept by lots and expiry dates.",
        },
        "nie",
    ),
    Column(
        "notes",
        ("uwagi", "notatki", "notes"),
        {"pl": "Uwagi", "en": "Notes"},
        {"pl": "Dowolny opis.", "en": "Any description."},
        "",
    ),
    Column(
        "quantity",
        ("ilość", "ilosc", "stan", "quantity"),
        {"pl": "Ilość", "en": "Quantity"},
        {
            "pl": "Stan początkowy: tyle przyjmie import do wybranego magazynu; puste — nic.",
            "en": "Opening stock: this much is received into the chosen warehouse; empty — none.",
        },
        "40",
    ),
    Column(
        "unit_cost",
        ("cena zakupu", "cena zakupu netto", "unit cost", "cost"),
        {"pl": "Cena zakupu", "en": "Purchase price"},
        {
            "pl": "Cena jednostkowa przyjmowanej ilości, np. 18,90.",
            "en": "The unit price of the quantity received, e.g. 18.90.",
        },
        "18,90",
    ),
    Column(
        "lot_number",
        ("partia", "numer partii", "lot"),
        {"pl": "Partia", "en": "Lot"},
        {
            "pl": "Numer partii przyjmowanej ilości — wymagany przy pozycji z partiami.",
            "en": "The lot of the quantity received — required for an item kept by lots.",
        },
        "",
    ),
    Column(
        "expires_on",
        ("ważność", "waznosc", "data ważności", "expires", "expiry"),
        {"pl": "Ważność", "en": "Expiry"},
        {"pl": "RRRR-MM-DD albo DD.MM.RRRR.", "en": "YYYY-MM-DD or DD.MM.YYYY."},
        "",
    ),
)
_BY_HEADER = {header: column for column in COLUMNS for header in column.headers}
_TEXT_COLUMNS = ("name", "sku", "ean", "category", "notes", "lot_number")
_UNITS = {
    **{unit.value: unit.value for unit in ItemUnit},
    "szt": "piece",
    "szt.": "piece",
    "sztuka": "piece",
    "pcs": "piece",
    "opak": "pack",
    "opak.": "pack",
    "opakowanie": "pack",
    "godz": "hour",
    "godz.": "hour",
    "h": "hour",
}
_YES = {"tak", "t", "yes", "y", "true", "1", "x"}
_NO = {"nie", "n", "no", "false", "0", ""}


class ImportIdempotencyConflict(APIException):
    status_code = 409
    default_code = "import_idempotency_conflict"
    default_detail = "Ten Idempotency-Key należy do importu innego pliku."


def template() -> dict[str, Any]:
    """The columns the import knows and a file to start from: a header and one
    example row, no formulas."""
    header = ";".join(column.headers[0] for column in COLUMNS)
    example = ";".join(column.example for column in COLUMNS)
    return {
        "columns": [
            {
                "key": column.key,
                "header": column.headers[0],
                "headers": list(column.headers),
                "title": dict(column.label),
                "description": dict(column.description),
                "mandatory": column.required,
                "example": column.example,
            }
            for column in COLUMNS
        ],
        "filename": "magazyn-import.csv",
        "csv": f"{header}\r\n{example}\r\n",
        "delimiter": ";",
        "max_rows": MAX_IMPORT_ROWS,
        "max_bytes": MAX_IMPORT_BYTES,
    }


# --- reading the text -------------------------------------------------------------------


def _problem(field_name: str, message: str, code: str) -> ValidationError:
    return ValidationError({field_name: [ErrorDetail(message, code=code)]})


def _read(content: str) -> tuple[list[str], list[tuple[int, dict[str, str]]], str, list[str]]:
    """(known columns, [(line, cells by column key)], delimiter, unknown headers)."""
    if len(content.encode()) > MAX_IMPORT_BYTES:
        raise _problem("content", f"Plik ma ponad {MAX_IMPORT_BYTES // 1000} kB.", "file_too_large")
    text = content.lstrip("﻿")
    first = next((line for line in text.splitlines() if line.strip()), "")
    if not first:
        raise _problem("content", "Plik jest pusty.", "empty")
    delimiter = max(DELIMITERS, key=first.count)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        table = [(reader.line_num, row) for row in reader if any(cell.strip() for cell in row)]
    except csv.Error as error:
        raise _problem("content", "Tego pliku nie da się odczytać jako CSV.", "not_csv") from error
    (_, header), body = table[0], table[1:]
    keys: list[str | None] = []
    unknown: list[str] = []
    for cell in header:
        column = _BY_HEADER.get(" ".join(cell.strip().lower().split()))
        if column is None:
            unknown.append(cell.strip())
            keys.append(None)
        elif column.key in keys:
            raise _problem(
                "content", f"Kolumna „{cell.strip()}” jest dwa razy.", "duplicate_column"
            )
        else:
            keys.append(column.key)
    known = [key for key in keys if key is not None]
    if "name" not in known:
        raise _problem(
            "content", "Brakuje kolumny „nazwa” w pierwszym wierszu.", "missing_name_column"
        )
    if len(body) > MAX_IMPORT_ROWS:
        raise _problem(
            "content", f"Plik ma ponad {MAX_IMPORT_ROWS} wierszy — podziel go.", "too_many_rows"
        )
    rows = [
        (
            line,
            {
                key: cells[index].strip()
                for index, key in enumerate(keys)
                if key and index < len(cells)
            },
        )
        for line, cells in body
    ]
    return known, rows, delimiter, unknown


def _decimal(raw: str) -> Decimal:
    value = Decimal(raw.replace(" ", "").replace(" ", "").replace(",", "."))
    if not value.is_finite():
        raise InvalidOperation
    return value


def _day(raw: str) -> date:
    for pattern in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, pattern).date()  # noqa: DTZ007 — a date, no time
        except ValueError:
            continue
    raise ValueError(raw)


# --- one row ----------------------------------------------------------------------------


@dataclass(slots=True)
class _Row:
    line: int
    name: str = ""
    sku: str = ""
    action: str = "create"
    item: InventoryItem | None = None
    values: dict[str, Any] = field(default_factory=dict)
    category_name: str = ""
    changes: list[str] = field(default_factory=list)
    quantity: Decimal | None = None
    unit_cost_minor: int | None = None
    lot_number: str = ""
    expires_on: date | None = None
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)

    def error(self, field_name: str, code: str, message: str) -> None:
        self.errors.append({"field": field_name, "code": code, "message": message})

    def warn(self, field_name: str, code: str, message: str) -> None:
        self.warnings.append({"field": field_name, "code": code, "message": message})


def _parse_row(line: int, cells: Mapping[str, str]) -> _Row:
    row = _Row(line=line, name=cells.get("name", ""), sku=cells.get("sku", ""))
    values = row.values
    for key in _TEXT_COLUMNS:
        if cells.get(key, "").startswith(FORMULA_START):
            row.warn(
                key,
                "formula_like",
                "Zaczyna się jak formuła arkusza — zostanie zapisane jako zwykły tekst.",
            )
    if not row.name:
        row.error("name", "required", "Podaj nazwę pozycji.")
    elif len(row.name) > 120:
        row.error("name", "max_length", "Nazwa ma najwyżej 120 znaków.")
    else:
        values["name"] = row.name
    for key, limit in (("sku", 64), ("ean", 14)):
        if key in cells:
            if len(cells[key]) > limit:
                row.error(key, "max_length", f"Najwyżej {limit} znaków.")
            elif cells[key]:
                values[key] = cells[key]
    if cells.get("notes"):
        values["notes"] = cells["notes"]
    if cells.get("category"):
        if len(cells["category"]) > 120:
            row.error("category", "max_length", "Nazwa kategorii ma najwyżej 120 znaków.")
        else:
            row.category_name = cells["category"]
    if cells.get("unit"):
        unit = _UNITS.get(cells["unit"].lower())
        if unit is None:
            row.error("unit", "invalid_choice", "Nieznana jednostka — np. szt., opak., ml, kg.")
        else:
            values["unit"] = unit
    if cells.get("vat_rate"):
        rate = cells["vat_rate"].lower().removesuffix("%").strip().removesuffix(".")
        if rate not in VatRate.values:
            row.error("vat_rate", "invalid_choice", "VAT to 23, 8, 5, 0 albo zw.")
        else:
            values["vat_rate"] = rate
    if "tracks_lots" in cells and cells["tracks_lots"]:
        answer = cells["tracks_lots"].lower()
        if answer in _YES:
            values["tracks_lots"] = True
        elif answer in _NO:
            values["tracks_lots"] = False
        else:
            row.error("tracks_lots", "invalid", "Wpisz „tak” albo „nie”.")
    for key, target, places in (
        ("minimum_quantity", "minimum_quantity", 3),
        ("quantity", "quantity", 3),
        ("sale_price", "sale_price_net_minor", 2),
        ("unit_cost", "unit_cost_minor", 2),
    ):
        raw = cells.get(key, "")
        if not raw:
            continue
        try:
            number = _decimal(raw)
        except InvalidOperation:
            row.error(key, "invalid", "To nie jest liczba.")
            continue
        if number < 0 or number != round(number, places) or number > Decimal(10) ** 8:
            row.error(key, "invalid", f"Liczba od zera, najwyżej {places} miejsca po przecinku.")
        elif target == "quantity":
            row.quantity = number or None
        elif target == "unit_cost_minor":
            row.unit_cost_minor = int(number * 100)
        elif target == "sale_price_net_minor":
            values[target] = int(number * 100)
        else:
            values[target] = number
    row.lot_number = cells.get("lot_number", "")
    if len(row.lot_number) > 64:
        row.error("lot_number", "max_length", "Numer partii ma najwyżej 64 znaki.")
    if cells.get("expires_on"):
        try:
            row.expires_on = _day(cells["expires_on"])
        except ValueError:
            row.error("expires_on", "invalid", "Data jako RRRR-MM-DD albo DD.MM.RRRR.")
    return row


def _plan(organization_id: UUID, rows: Sequence[_Row]) -> list[str]:
    """Matches each row to the catalogue and says what it would do; no writes.
    Returns the names of the categories the import would create."""
    items = list(
        InventoryItem.all_objects.filter(organization_id=organization_id).select_related("category")
    )
    by_sku = {item.sku.lower(): item for item in items if item.sku}
    by_name = {item.name.lower(): item for item in items}
    categories = {
        category.name.lower(): category
        for category in InventoryCategory.all_objects.filter(organization_id=organization_id)
    }
    new_categories: dict[str, str] = {}
    seen_names: dict[str, int] = {}
    seen_skus: dict[str, int] = {}
    for row in rows:
        if not row.name:
            row.action = "error"
            continue
        name, sku = row.name.lower(), row.sku.lower()
        for seen, key, field_name in ((seen_names, name, "name"), (seen_skus, sku, "sku")):
            if key and key in seen:
                row.error(field_name, "duplicate_in_file", f"To samo co w wierszu {seen[key]}.")
            elif key:
                seen[key] = row.line
        # By SKU first: the name of an item the company already has may change.
        existing = (by_sku.get(sku) if sku else None) or by_name.get(name)
        if existing is not None:
            taken = by_name.get(name)
            if taken is not None and taken.id != existing.id:
                row.error("name", "name_taken", "Tę nazwę ma już inna pozycja katalogu.")
        row.item = existing
        if row.category_name:
            known = categories.get(row.category_name.lower())
            if known is not None:
                row.values["category"] = known
            else:
                new_categories.setdefault(row.category_name.lower(), row.category_name)
        tracks = row.values.get(
            "tracks_lots", existing.tracks_lots if existing is not None else False
        )
        if row.quantity is not None:
            if tracks and not row.lot_number:
                row.error("lot_number", "lot_required", "Pozycja z partiami: podaj numer partii.")
            if row.unit_cost_minor is None:
                row.warn(
                    "unit_cost",
                    "no_cost",
                    "Bez ceny zakupu ta ilość wejdzie z wartością 0.",
                )
        if not tracks and (row.lot_number or row.expires_on):
            row.error("lot_number", "lots_not_tracked", "Ta pozycja nie prowadzi partii.")
        if existing is None:
            row.action, row.changes = (
                "create",
                sorted(row.values)
                + (["category"] if row.category_name and "category" not in row.values else []),
            )
        else:
            row.changes = sorted(
                key
                for key, value in row.values.items()
                if (
                    existing.category_id != value.id
                    if key == "category"
                    else getattr(existing, key) != value
                )
            ) + (["category"] if row.category_name.lower() in new_categories else [])
            row.action = "update" if row.changes else "unchanged"
        if row.errors:
            row.action = "error"
    return list(new_categories.values())


def _row_payload(row: _Row) -> dict[str, Any]:
    return {
        "line": row.line,
        "action": row.action,
        "name": row.name,
        "sku": row.sku,
        "item_id": row.item.id if row.item is not None else None,
        "changes": row.changes,
        "quantity": row.quantity,
        "problems": row.errors,
        "warnings": row.warnings,
    }


def _result(
    rows: Sequence[_Row],
    *,
    columns: Sequence[str],
    unknown: Sequence[str],
    delimiter: str,
    new_categories: Sequence[str],
    location: StockLocation,
) -> dict[str, Any]:
    count = {action: sum(1 for row in rows if row.action == action) for action in ACTIONS}
    return {
        "applied": False,
        "replayed": False,
        "summary": {
            "rows": len(rows),
            "created": count["create"],
            "updated": count["update"],
            "unchanged": count["unchanged"],
            "invalid": count["error"],
            "stock_lines": sum(
                1 for row in rows if row.quantity is not None and row.action != "error"
            ),
            "new_categories": list(new_categories),
        },
        "columns": list(columns),
        "unknown_columns": list(unknown),
        "delimiter": "tab" if delimiter == "\t" else delimiter,
        "location_id": location.id,
        "document": None,
        "rows": [_row_payload(row) for row in rows],
    }


ACTIONS = ("create", "update", "unchanged", "error")


# --- the operation ------------------------------------------------------------------------


@transaction.atomic
def import_items(
    *,
    request: HttpRequest,
    content: str,
    location_id: UUID | None = None,
    idempotency_key: str = "",
    preview: bool = False,
) -> dict[str, Any]:
    """Previews or saves a CSV of items; see the module's docstring.

    A save with a problem in any row saves nothing and answers 400 with the
    rows' problems (`rows[<line>].<column>`). A repeated `idempotency_key`
    answers the first save's summary again (`replayed`); the key with another
    file is 409 `import_idempotency_conflict`.
    """
    context = _manage_context()
    organization_id = context.organization_id
    digest = hashlib.sha256(content.encode()).hexdigest()
    if not preview:
        key = idempotency_key.strip()
        if not key or len(key) > 120:
            raise _problem(
                "idempotency_key",
                "Nagłówek Idempotency-Key jest wymagany (do 120 znaków).",
                "required",
            )
        earlier = OrganizationAuditEntry.objects.filter(
            organization_id=organization_id,
            action=OrganizationAuditAction.INVENTORY_IMPORTED,
            metadata__idempotency_key=key,
        ).first()
        if earlier is not None:
            if earlier.metadata.get("content_sha256") != digest:
                raise ImportIdempotencyConflict
            return {**earlier.metadata["result"], "replayed": True}
    location = (
        _get(StockLocation, organization_id, location_id)
        if location_id is not None
        else default_warehouse(organization_id)
    )
    if location.kind != LocationKind.WAREHOUSE:
        raise _problem(
            "location_id", "Stan początkowy przyjmuje magazyn, nie zapas osoby.", "invalid"
        )
    columns, cells, delimiter, unknown = _read(content)
    rows = [_parse_row(line, row) for line, row in cells]
    new_categories = _plan(organization_id, rows)
    result = _result(
        rows,
        columns=columns,
        unknown=unknown,
        delimiter=delimiter,
        new_categories=new_categories,
        location=location,
    )
    if preview:
        return result
    broken = [row for row in rows if row.errors]
    if broken:
        raise ValidationError(
            {
                f"rows[{row.line}].{problem['field']}": [
                    ErrorDetail(problem["message"], code=problem["code"])
                ]
                for row in broken[:REPORTED_ERRORS]
                for problem in row.errors
            },
            code="import_has_errors",
        )
    document = _write(request, organization_id, rows, location, key)
    result["applied"] = True
    result["document"] = (
        {"id": str(document.id), "number": document.number} if document is not None else None
    )
    for row, payload in zip(rows, result["rows"], strict=True):
        payload["item_id"] = row.item.id if row.item is not None else None
    summary = result["summary"]
    _audit(
        request,
        organization_id,
        OrganizationAuditAction.INVENTORY_IMPORTED,
        "inventory_import",
        document.id if document is not None else uuid.uuid5(IMPORT_NAMESPACE, key),
        {
            "idempotency_key": key,
            "content_sha256": digest,
            "created": summary["created"],
            "updated": summary["updated"],
            "stock_lines": summary["stock_lines"],
            "document": result["document"]["number"] if result["document"] else "",
            # What a repeat of the key answers: the counts, never the rows.
            "result": {
                **{name: value for name, value in result.items() if name != "rows"},
                "location_id": str(location.id),
                "rows": [],
            },
        },
    )
    return result


def _write(
    request: HttpRequest,
    organization_id: UUID,
    rows: Sequence[_Row],
    location: StockLocation,
    key: str,
) -> Any:
    """Categories, items, then one posted PW with every row's opening stock."""
    from .models import StockDocument  # noqa: PLC0415

    context = _manage_context()
    currency = _organization(organization_id).currency
    categories = {
        category.name.lower(): category
        for category in InventoryCategory.all_objects.filter(organization_id=organization_id)
    }
    keys = set(
        InventoryCategory.all_objects.filter(organization_id=organization_id).values_list(
            "key", flat=True
        )
    )
    for row in rows:
        name = row.category_name
        if name and name.lower() not in categories:
            base = slugify(name)[:56] or "category"
            slug, number = base, 1
            while slug in keys:
                number += 1
                slug = f"{base}-{number}"
            keys.add(slug)
            categories[name.lower()] = InventoryCategory.all_objects.create(
                organization_id=organization_id, key=slug, name=name
            )
        if name:
            row.values["category"] = categories[name.lower()]
        if row.item is None:
            row.item = InventoryItem.all_objects.create(
                organization_id=organization_id, currency=currency, **row.values
            )
        elif row.action == "update":
            for field_name, value in row.values.items():
                setattr(row.item, field_name, value)
            row.item.save(update_fields=[*row.values, "updated_at"])
    lines = [
        LineInput(
            item_id=row.item.id,
            quantity=row.quantity,
            unit_price_minor=row.unit_cost_minor,
            lot_number=row.lot_number,
            expires_on=row.expires_on,
        )
        for row in rows
        if row.quantity is not None and row.item is not None
    ]
    if not lines:
        return None
    document = StockDocument.all_objects.create(
        # One document per key: whatever retries, the stock is received once.
        id=uuid.uuid5(IMPORT_NAMESPACE, f"{organization_id}:{key}"),
        organization_id=organization_id,
        kind=DocumentKind.PW,
        document_date=organization_today(organization_id),
        target_location=location,
        note="Stan początkowy z importu CSV",
        created_by_id=context.actor_id,
    )
    _write_lines(document, lines)
    _post(document, actor_id=context.actor_id, allow_negative=True)
    return document
