from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import DocumentKind, DocumentStatus, ItemUnit, LocationKind, VatRate


def _quantity(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=12, decimal_places=3, **kwargs)


class InventoryCategorySerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    key = serializers.CharField(read_only=True)
    name = serializers.CharField(max_length=120)
    #: Startowa kategoria produktu: można zmienić nazwę, nie usunąć.
    system = serializers.BooleanField(read_only=True)
    expiring_days = serializers.IntegerField(
        min_value=1,
        max_value=365,
        allow_null=True,
        required=False,
        help_text="How many days before its expiry date a lot of this category counts as "
        "expiring (1–365); null: the company's number (setting inventory.lots.expiring_days).",
    )


class InventoryCategoryUpdateSerializer(serializers.Serializer[Any]):
    """Only the fields sent change."""

    name = serializers.CharField(
        max_length=120, required=False, help_text="The category's name, unique in the company."
    )
    expiring_days = serializers.IntegerField(
        min_value=1,
        max_value=365,
        allow_null=True,
        required=False,
        help_text="Days before expiry a lot of this category counts as expiring (1–365); "
        "null returns to the company's number.",
    )


class StockLocationSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    kind = serializers.ChoiceField(choices=LocationKind.choices, read_only=True)
    name = serializers.CharField(max_length=120)
    holder_id = serializers.UUIDField(read_only=True, allow_null=True)
    #: Czyj to zapas — z konta osoby, nie z magazynu.
    holder_name = serializers.SerializerMethodField()
    is_default = serializers.BooleanField(read_only=True)
    active = serializers.BooleanField(required=False)

    def get_holder_name(self, location: Any) -> str | None:
        holder = location.holder
        if holder is None:
            return None
        return " ".join(filter(None, [holder.first_name, holder.last_name])) or holder.email


class SupplierSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(max_length=160)
    tax_id = serializers.CharField(max_length=20, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    active = serializers.BooleanField(required=False)


class InventoryItemSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(max_length=120)
    sku = serializers.CharField(max_length=64, required=False, allow_blank=True)
    ean = serializers.CharField(max_length=14, required=False, allow_blank=True)
    category_id = serializers.UUIDField(read_only=True, allow_null=True)
    #: Klucz kategorii — produkt rozpoznaje po nim swoje pozycje.
    category = serializers.CharField(
        source="category.key", read_only=True, allow_null=True, default=None
    )
    category_name = serializers.CharField(
        source="category.name", read_only=True, allow_null=True, default=None
    )
    unit = serializers.ChoiceField(choices=ItemUnit.choices)
    minimum_quantity = _quantity()
    #: Średnia ważona cena zakupu w groszach; rozchód wycenia się po niej.
    #: `null` dla kogoś bez `inventory.manage`: ceny zakupu zna tylko ten, kto
    #: prowadzi magazyn (odpowiedź Macieja 43a, UX-024).
    average_cost_minor = serializers.IntegerField(read_only=True, allow_null=True)
    sale_price_net_minor = serializers.IntegerField(allow_null=True, required=False)
    vat_rate = serializers.ChoiceField(choices=VatRate.choices)
    currency = serializers.CharField(read_only=True)
    #: Pozycja standardowa produktu: można ją zmienić i ukryć, nie usunąć.
    system_key = serializers.CharField(read_only=True)
    #: Partie i daty ważności: przyjęcie podaje partię, rozchód bierze je wg ważności.
    tracks_lots = serializers.BooleanField()
    active = serializers.BooleanField()
    notes = serializers.CharField(allow_blank=True)

    def to_representation(self, instance: Any) -> dict[str, Any]:
        data = super().to_representation(instance)
        if not self.context.get("costs", False):
            data["average_cost_minor"] = None
        return data


class InventoryItemInputSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=120)
    sku = serializers.CharField(max_length=64, required=False, allow_blank=True)
    ean = serializers.CharField(max_length=14, required=False, allow_blank=True)
    #: Id kategorii albo jej klucz.
    category = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    unit = serializers.ChoiceField(choices=ItemUnit.choices, required=False)
    minimum_quantity = _quantity(required=False, min_value=0)
    sale_price_net_minor = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    vat_rate = serializers.ChoiceField(choices=VatRate.choices, required=False)
    tracks_lots = serializers.BooleanField(required=False)
    active = serializers.BooleanField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


LOT_STATUS = (
    ("expired", "Po terminie"),
    ("expiring", "Kończy się ważność"),
    ("ok", "Ważna"),
    ("no_date", "Bez daty ważności"),
)


class InventoryBalanceSerializer(serializers.Serializer[Any]):
    """Ile czego leży w jednym miejscu; dostępne = stan − zarezerwowane."""

    item_id = serializers.UUIDField()
    item_name = serializers.CharField(source="item.name")
    sku = serializers.CharField(source="item.sku")
    category = serializers.CharField(source="item.category.key", allow_null=True, default=None)
    category_name = serializers.CharField(
        source="item.category.name", allow_null=True, default=None
    )
    unit = serializers.CharField(source="item.unit")
    location_id = serializers.UUIDField()
    location_name = serializers.CharField(source="location.name")
    holder_id = serializers.UUIDField(source="location.holder_id", allow_null=True)
    quantity = _quantity()
    reserved = _quantity()
    available = serializers.SerializerMethodField()
    #: Minimum, które tu obowiązuje: ustawione przy miejscu albo (w magazynie)
    #: minimum pozycji; `null` — tu bez minimum.
    minimum_quantity = serializers.SerializerMethodField()
    #: Minimum ustawione przy tym miejscu; `null` — dziedziczy (M4).
    place_minimum = _quantity(source="minimum_quantity", allow_null=True)
    below_minimum = serializers.SerializerMethodField()
    tracks_lots = serializers.BooleanField(source="item.tracks_lots")
    #: Najbliższy termin partii, które tu leżą — i co z niego wynika.
    nearest_expiry = serializers.SerializerMethodField()
    lot_status = serializers.SerializerMethodField()
    updated_at = serializers.DateTimeField()

    def get_available(self, balance: Any) -> str:
        return f"{balance.quantity - balance.reserved:.3f}"

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=3, allow_null=True))
    def get_minimum_quantity(self, balance: Any) -> str | None:
        from .services import effective_minimum  # noqa: PLC0415

        minimum = effective_minimum(balance)
        return None if minimum is None else f"{minimum:.3f}"

    @extend_schema_field(serializers.BooleanField())
    def get_below_minimum(self, balance: Any) -> bool:
        from .services import below_minimum  # noqa: PLC0415

        return below_minimum(balance)

    def _nearest(self, balance: Any) -> dict[str, Any] | None:
        nearest: dict[tuple[Any, Any], dict[str, Any]] = self.context.get("nearest", {})
        return nearest.get((balance.item_id, balance.location_id))

    @extend_schema_field(serializers.DateField(allow_null=True))
    def get_nearest_expiry(self, balance: Any) -> Any:
        found = self._nearest(balance)
        return found["expires_on"] if found else None

    @extend_schema_field(serializers.ChoiceField(choices=LOT_STATUS, allow_null=True))
    def get_lot_status(self, balance: Any) -> str | None:
        found = self._nearest(balance)
        return found["status"] if found else None


class InventoryLotStockSerializer(serializers.Serializer[Any]):
    """Partia, która gdzieś leży: ile i jak z jej ważnością."""

    lot_id = serializers.UUIDField()
    item_id = serializers.UUIDField()
    item_name = serializers.CharField()
    unit = serializers.CharField()
    number = serializers.CharField()
    expires_on = serializers.DateField(allow_null=True)
    status = serializers.ChoiceField(choices=LOT_STATUS)
    location_id = serializers.UUIDField()
    location_name = serializers.CharField()
    holder_id = serializers.UUIDField(allow_null=True)
    quantity = _quantity()


class InventoryMovementSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    item_id = serializers.UUIDField()
    item_name = serializers.CharField(source="item.name")
    location_id = serializers.UUIDField()
    location_name = serializers.CharField(source="location.name")
    document_id = serializers.UUIDField()
    document_number = serializers.CharField(source="document.number")
    kind = serializers.ChoiceField(choices=DocumentKind.choices)
    quantity = _quantity()
    #: `null` for whoever does not run the warehouse (answer 43a).
    unit_cost_minor = serializers.IntegerField(allow_null=True)
    created_at = serializers.DateTimeField()

    def to_representation(self, instance: Any) -> dict[str, Any]:
        data = super().to_representation(instance)
        if not self.context.get("costs", False):
            data["unit_cost_minor"] = None
        return data


class MovedLotSerializer(serializers.Serializer[Any]):
    number = serializers.CharField()
    expires_on = serializers.DateField(allow_null=True)
    quantity = _quantity()


class StockDocumentLineSerializer(serializers.Serializer[Any]):
    item_id = serializers.UUIDField()
    item_name = serializers.CharField(source="item.name")
    quantity = _quantity()
    unit_price_minor = serializers.IntegerField(allow_null=True)
    #: Waluta ceny: ta, w której założono pozycję.
    currency = serializers.CharField(source="item.currency", read_only=True)
    #: Partia wiersza: przyjęta albo wskazana do rozchodu.
    lot_id = serializers.UUIDField(allow_null=True)
    lot_number = serializers.CharField(source="lot.number", allow_null=True, default=None)
    expires_on = serializers.DateField(source="lot.expires_on", allow_null=True, default=None)
    #: Co naprawdę zeszło albo przybyło — partie z ruchów zatwierdzonego dokumentu.
    moved_lots = serializers.SerializerMethodField()
    note = serializers.CharField()

    @extend_schema_field(MovedLotSerializer(many=True))
    def get_moved_lots(self, line: Any) -> list[dict[str, Any]]:
        document = line.document
        place = document.source_location_id or document.target_location_id
        totals: dict[Any, dict[str, Any]] = {}
        for movement in document.movements.all():
            if movement.item_id != line.item_id or movement.lot is None:
                continue
            if movement.location_id != place:
                continue
            lot = movement.lot
            row = totals.setdefault(
                movement.lot_id,
                {"number": lot.number, "expires_on": lot.expires_on, "quantity": 0},
            )
            row["quantity"] += abs(movement.quantity)
        return list(totals.values())


class StockDocumentLineInputSerializer(serializers.Serializer[Any]):
    item_id = serializers.UUIDField()
    quantity = _quantity(min_value=0)
    unit_price_minor = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    #: Partia do rozchodu; bez niej rozchód bierze partie wg ważności.
    lot_id = serializers.UUIDField(required=False, allow_null=True)
    #: Numer partii — przyjęcie i inwentaryzacja zakładają nową.
    lot_number = serializers.CharField(max_length=64, required=False, allow_blank=True)
    expires_on = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)


class StockDocumentSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=DocumentKind.choices)
    status = serializers.ChoiceField(choices=DocumentStatus.choices)
    #: Pusty do zatwierdzenia; potem `RODZAJ/RRRR/NNNN`.
    number = serializers.CharField()
    document_date = serializers.DateField()
    source_location_id = serializers.UUIDField(allow_null=True)
    target_location_id = serializers.UUIDField(allow_null=True)
    supplier_id = serializers.UUIDField(allow_null=True)
    counterparty = serializers.CharField()
    corrects_id = serializers.UUIDField(allow_null=True)
    source = serializers.CharField()  # type: ignore[assignment]
    source_reference = serializers.CharField()
    note = serializers.CharField()
    created_by_id = serializers.UUIDField()
    posted_at = serializers.DateTimeField(allow_null=True)
    lines = StockDocumentLineSerializer(many=True, source="lines.all")


class StockDocumentInputSerializer(serializers.Serializer[Any]):
    #: Nadaje klient; powtórka z tym samym id nie tworzy drugiego dokumentu.
    id = serializers.UUIDField(required=False)
    kind = serializers.ChoiceField(choices=DocumentKind.choices)
    document_date = serializers.DateField(required=False)
    source_location_id = serializers.UUIDField(required=False, allow_null=True)
    target_location_id = serializers.UUIDField(required=False, allow_null=True)
    supplier_id = serializers.UUIDField(required=False, allow_null=True)
    counterparty = serializers.CharField(max_length=160, required=False, allow_blank=True)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)
    lines = StockDocumentLineInputSerializer(many=True, required=False)


class StockDocumentCorrectionSerializer(serializers.Serializer[Any]):
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)


class InventoryReceiptInputSerializer(serializers.Serializer[Any]):
    #: Nadaje klient; powtórka z tym samym id nie tworzy drugiego dokumentu.
    id = serializers.UUIDField(required=False)
    item_id = serializers.UUIDField()
    quantity = _quantity(min_value=0)
    unit_cost_minor = serializers.IntegerField(min_value=0, default=0)
    lot_number = serializers.CharField(max_length=64, required=False, allow_blank=True)
    expires_on = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)


class InventoryIssueInputSerializer(serializers.Serializer[Any]):
    #: Nadaje klient; powtórka z tym samym id nie tworzy drugiego dokumentu.
    id = serializers.UUIDField(required=False)
    item_id = serializers.UUIDField()
    holder_id = serializers.UUIDField()
    quantity = _quantity(min_value=0)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)


class InventoryAdjustInputSerializer(serializers.Serializer[Any]):
    #: Nadaje klient; powtórka z tym samym id nie tworzy drugiego dokumentu.
    id = serializers.UUIDField(required=False)
    item_id = serializers.UUIDField()
    holder_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    quantity = _quantity()
    note = serializers.CharField(max_length=240)


class LowStockRowSerializer(serializers.Serializer[Any]):
    """One item at or below its minimum in one place (available ≤ minimum)."""

    item_id = serializers.UUIDField()
    item_name = serializers.CharField()
    unit = serializers.ChoiceField(choices=ItemUnit.choices)
    location_id = serializers.UUIDField()
    location_name = serializers.CharField()
    location_kind = serializers.ChoiceField(choices=LocationKind.choices)
    holder_id = serializers.UUIDField(
        allow_null=True, help_text="Whose own stock this is; null for a warehouse."
    )
    quantity = _quantity(help_text="On hand in the place.")
    available = _quantity(help_text="On hand minus what is reserved for visits and orders.")
    minimum = _quantity(help_text="The minimum in force here.")
    missing = _quantity(help_text="How much is needed to be back at the minimum.")


class PlaceMinimumInputSerializer(serializers.Serializer[Any]):
    item_id = serializers.UUIDField(help_text="The item.")
    location_id = serializers.UUIDField(help_text="The warehouse or the person's stock.")
    minimum_quantity = _quantity(
        min_value=0,
        allow_null=True,
        help_text="The minimum in this place; 0: no minimum here; null: back to the item's "
        "minimum (a warehouse) or none (a person's stock).",
    )


# --- reports (phase 10b) -----------------------------------------------------------------

STOCK_VALUE_GROUPS = (
    ("item", "By item"),
    ("category", "By category"),
    ("location", "By place"),
)
USAGE_GROUPS = (
    ("item", "By item"),
    ("person", "By person"),
    ("service", "By service"),
    ("customer", "By customer"),
    ("visit", "Visit by visit"),
)


class StockValueQuerySerializer(serializers.Serializer[Any]):
    group = serializers.ChoiceField(
        choices=STOCK_VALUE_GROUPS, default="item", help_text="What a row is."
    )
    location_id = serializers.UUIDField(
        required=False, default=None, help_text="Only this place; without it, the whole company."
    )


class StockValueRowSerializer(serializers.Serializer[Any]):
    key = serializers.CharField(
        allow_blank=True,
        help_text="The item's, category's or place's id; empty: items without a category.",
    )
    name = serializers.CharField(
        allow_blank=True, help_text="The row's name; empty with an empty key."
    )
    kind = serializers.CharField(
        allow_blank=True, help_text="For a place: warehouse or person; else empty."
    )
    quantity = _quantity(allow_null=True, help_text="Only when grouped by item.")
    unit = serializers.CharField(allow_blank=True)
    average_cost_minor = serializers.IntegerField(
        allow_null=True, help_text="The item's average purchase cost; only by item."
    )
    value_minor = serializers.IntegerField(help_text="Quantity × average cost, minor units.")
    currency = serializers.CharField()


class StockValueTotalSerializer(serializers.Serializer[Any]):
    currency = serializers.CharField()
    value_minor = serializers.IntegerField()


class StockValueReportSerializer(serializers.Serializer[Any]):
    group = serializers.ChoiceField(choices=STOCK_VALUE_GROUPS)
    rows = StockValueRowSerializer(many=True)
    totals = StockValueTotalSerializer(many=True)


class UsageQuerySerializer(serializers.Serializer[Any]):
    group = serializers.ChoiceField(
        choices=USAGE_GROUPS, default="item", help_text="What a row is."
    )
    # `from` is a keyword: declared in get_fields.
    to = serializers.DateField(help_text="The last day of the period, the company's day.")
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=200, default=50)

    def get_fields(self) -> dict[str, Any]:
        fields = super().get_fields()
        fields["from"] = serializers.DateField(
            help_text="The first day of the period, the company's day."
        )
        return fields


class UsageRowSerializer(serializers.Serializer[Any]):
    key = serializers.CharField(
        allow_blank=True,
        help_text="The id of the item, person, service, customer or visit. Empty: usage "
        "outside any visit (adjustments, losses); `hidden` for a customer this reader may "
        "not see.",
    )
    name = serializers.CharField(
        allow_blank=True, help_text="The row's name; empty with an empty key."
    )
    quantity = _quantity(allow_null=True, help_text="Only when grouped by item.")
    unit = serializers.CharField(allow_blank=True)
    cost_minor = serializers.IntegerField(
        help_text="What it cost the company: each movement at the cost it carried."
    )
    sold_minor = serializers.IntegerField(
        help_text="What sales to customers (WZ) were priced at, net."
    )
    currency = serializers.CharField()
    documents = serializers.IntegerField(help_text="How many stock documents make the row.")
    at = serializers.DateTimeField(allow_null=True, help_text="A visit's start; else null.")
    service_name = serializers.CharField(allow_blank=True, help_text="A visit's service.")
    customer_name = serializers.CharField(
        allow_blank=True, help_text="A visit's customer, for a reader who may see it."
    )
    person_name = serializers.CharField(allow_blank=True, help_text="Who led the visit.")


class UsageTotalSerializer(serializers.Serializer[Any]):
    currency = serializers.CharField()
    cost_minor = serializers.IntegerField()
    sold_minor = serializers.IntegerField()


class UsageReportSerializer(serializers.Serializer[Any]):
    group = serializers.ChoiceField(choices=USAGE_GROUPS)
    total = serializers.IntegerField(help_text="How many rows the report has in all.")
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    rows = UsageRowSerializer(many=True)
    totals = UsageTotalSerializer(many=True, help_text="The whole period, every row, per currency.")

    def get_fields(self) -> dict[str, Any]:
        fields = super().get_fields()
        fields["from"] = serializers.DateField()
        fields["to"] = serializers.DateField()
        return fields


# --- CSV import (phase 10c) ----------------------------------------------------------------

IMPORT_ACTIONS = (
    ("create", "A new item"),
    ("update", "An existing item changes"),
    ("unchanged", "An existing item stays as it is"),
    ("error", "The row has a problem; nothing is saved while any row has one"),
)


class ImportInputSerializer(serializers.Serializer[Any]):
    content = serializers.CharField(
        trim_whitespace=False,
        help_text="The CSV as text: a header row, then one item per row. Columns by header "
        "(Polish or English, see the template), `;`, `,` or a tab between cells, a decimal "
        "comma or point. A cell starting with = + - or @ is kept as plain text.",
    )
    location_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="The warehouse that receives rows with a quantity; null: the main one.",
    )


class ImportProblemSerializer(serializers.Serializer[Any]):
    field = serializers.CharField(help_text="The column's key, e.g. unit.")
    code = serializers.CharField()
    message = serializers.CharField()


class ImportRowSerializer(serializers.Serializer[Any]):
    line = serializers.IntegerField(help_text="The row's line in the file; the header is 1.")
    action = serializers.ChoiceField(choices=IMPORT_ACTIONS)
    name = serializers.CharField(allow_blank=True)
    sku = serializers.CharField(allow_blank=True)
    item_id = serializers.UUIDField(
        allow_null=True, help_text="The catalogue item the row matched or created."
    )
    changes = serializers.ListField(
        child=serializers.CharField(), help_text="The item's fields the row sets or changes."
    )
    quantity = _quantity(allow_null=True, help_text="Opening stock the row receives; null: none.")
    problems = ImportProblemSerializer(
        many=True, help_text="Why the row cannot be saved; empty when it can."
    )
    warnings = ImportProblemSerializer(
        many=True, help_text="What to look at before saving; they do not stop the save."
    )


class ImportSummarySerializer(serializers.Serializer[Any]):
    rows = serializers.IntegerField()
    created = serializers.IntegerField(help_text="New items.")
    updated = serializers.IntegerField(help_text="Existing items the file changes.")
    unchanged = serializers.IntegerField()
    invalid = serializers.IntegerField(help_text="Rows with a problem.")
    stock_lines = serializers.IntegerField(help_text="Rows that receive opening stock.")
    new_categories = serializers.ListField(
        child=serializers.CharField(), help_text="Categories the import creates."
    )


class ImportDocumentSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    number = serializers.CharField()


class ImportResultSerializer(serializers.Serializer[Any]):
    applied = serializers.BooleanField(help_text="False for a preview: nothing was saved.")
    replayed = serializers.BooleanField(
        help_text="True when this Idempotency-Key was already saved: the first save's "
        "summary, without rows."
    )
    summary = ImportSummarySerializer()
    columns = serializers.ListField(
        child=serializers.CharField(), help_text="The columns recognised in the header."
    )
    unknown_columns = serializers.ListField(
        child=serializers.CharField(), help_text="Headers the import does not know; ignored."
    )
    delimiter = serializers.CharField()
    location_id = serializers.UUIDField()
    document = ImportDocumentSerializer(
        allow_null=True, help_text="The posted PW with the opening stock, once saved."
    )
    rows = ImportRowSerializer(many=True)


class ImportColumnSerializer(serializers.Serializer[Any]):
    key = serializers.CharField()
    header = serializers.CharField(help_text="The header the template uses.")
    headers = serializers.ListField(
        child=serializers.CharField(), help_text="Every header the import accepts for it."
    )
    title = serializers.DictField(child=serializers.CharField(), help_text="pl and en.")
    description = serializers.DictField(child=serializers.CharField(), help_text="pl and en.")
    mandatory = serializers.BooleanField()
    example = serializers.CharField(allow_blank=True)


class ImportTemplateSerializer(serializers.Serializer[Any]):
    columns = ImportColumnSerializer(many=True)
    filename = serializers.CharField()
    csv = serializers.CharField(help_text="A file to start from: the header and one example row.")
    delimiter = serializers.CharField()
    max_rows = serializers.IntegerField()
    max_bytes = serializers.IntegerField()
