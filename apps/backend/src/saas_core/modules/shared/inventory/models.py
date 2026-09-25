"""Magazyn firmy (ADR-055): co firma ma, gdzie to leży i skąd się wzięło.

Stan nie jest polem, które ktoś ustawia: wynika z ruchów, a ruchy powstają
wyłącznie z zatwierdzonych dokumentów (PZ, WZ, RW, PW, MM, INW). Dokument
zatwierdzony się nie zmienia — pomyłkę prostuje korekta. `InventoryBalance` to
wyliczona suma trzymana obok księgi, żeby ekran w oborze albo w salonie nie
sumował historii; ma też część zarezerwowaną pod przyszłe wizyty i zamówienia.

Miejscem jest magazyn firmy albo zapas osoby: korektor wyjeżdża z pakietem i z
niego się rozlicza (decyzja z 21.09), serwisant z busem tak samo.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel


class ItemUnit(models.TextChoices):
    PIECE = "piece", "Sztuka"
    PACK = "pack", "Opakowanie"
    MILLILITRE = "ml", "Mililitr"
    LITRE = "l", "Litr"
    GRAM = "g", "Gram"
    KILOGRAM = "kg", "Kilogram"
    METRE = "m", "Metr"
    HOUR = "hour", "Godzina"


class VatRate(models.TextChoices):
    STANDARD = "23", "23%"
    REDUCED = "8", "8%"
    SUPER_REDUCED = "5", "5%"
    ZERO = "0", "0%"
    EXEMPT = "zw", "zw."


class LocationKind(models.TextChoices):
    WAREHOUSE = "warehouse", "Magazyn"
    PERSON = "person", "Zapas osoby"


class DocumentKind(models.TextChoices):
    PZ = "PZ", "Przyjęcie zewnętrzne"
    WZ = "WZ", "Wydanie zewnętrzne"
    RW = "RW", "Rozchód wewnętrzny"
    PW = "PW", "Przychód wewnętrzny"
    MM = "MM", "Przesunięcie międzymagazynowe"
    INW = "INW", "Inwentaryzacja"


class DocumentStatus(models.TextChoices):
    DRAFT = "draft", "Szkic"
    POSTED = "posted", "Zatwierdzony"


class ReservationStatus(models.TextChoices):
    ACTIVE = "active", "Aktywna"
    CONSUMED = "consumed", "Zużyta"
    RELEASED = "released", "Zwolniona"


class InventoryCategory(TenantScopedModel):
    """Kategoria towaru w firmie. Startowe deklaruje produkt; własne dopisuje firma."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    key = models.SlugField(max_length=64)
    name = models.CharField(max_length=120)
    #: Startowa z deklaracji produktu: można zmienić nazwę, nie można usunąć.
    system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "key"], name="inventory_category_key_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "name"], name="inventory_category_name_uq"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class StockLocation(TenantScopedModel):
    """Magazyn firmy albo zapas jednej osoby."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    kind = models.CharField(max_length=16, choices=LocationKind)
    name = models.CharField(max_length=120)
    holder = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="stock_locations",
        null=True,
        blank=True,
    )
    #: Magazyn główny: tam trafia przyjęcie bez wskazanego miejsca.
    is_default = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "kind", "name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "holder"],
                condition=models.Q(holder__isnull=False),
                name="inventory_location_holder_uq",
            ),
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(is_default=True),
                name="inventory_location_default_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(kind=LocationKind.PERSON, holder__isnull=False, is_default=False)
                    | models.Q(kind=LocationKind.WAREHOUSE, holder__isnull=True)
                ),
                name="inventory_location_kind_ck",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Supplier(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=160)
    tax_id = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "name", "id")
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="inventory_supplier_uq"),
        ]

    def __str__(self) -> str:
        return self.name


class InventoryItem(TenantScopedModel):
    """Pozycja katalogu = jeden towar (SKU). Sklep pokaże te same pozycje."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=120)
    sku = models.CharField(max_length=64, blank=True)
    ean = models.CharField(max_length=14, blank=True)
    category = models.ForeignKey(
        InventoryCategory,
        on_delete=models.PROTECT,
        related_name="items",
        null=True,
        blank=True,
    )
    unit = models.CharField(max_length=8, choices=ItemUnit, default=ItemUnit.PIECE)
    #: Poniżej tej wartości magazyn prosi o uzupełnienie; 0 wyłącza próg.
    minimum_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    #: Średnia ważona cena zakupu w groszach; rozchód wycenia się po niej.
    average_cost_minor = models.PositiveIntegerField(default=0)
    #: Cena sprzedaży netto w groszach: przy wizycie „sprzedaż klientowi” i w sklepie.
    sale_price_net_minor = models.PositiveIntegerField(null=True, blank=True)
    vat_rate = models.CharField(max_length=2, choices=VatRate, default=VatRate.STANDARD)
    currency = models.CharField(max_length=3, default="PLN")
    #: Klucz pozycji standardowej z deklaracji produktu; taka pozycja nie znika.
    system_key = models.CharField(max_length=64, blank=True)
    #: Partie i daty ważności (leki, kosmetyki): każdy ruch niesie partię, a
    #: rozchód bez wskazanej partii bierze tę, która najwcześniej traci ważność.
    tracks_lots = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="inventory_item_org_name_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "sku"],
                condition=~models.Q(sku=""),
                name="inventory_item_sku_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "system_key"],
                condition=~models.Q(system_key=""),
                name="inventory_item_system_key_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(minimum_quantity__gte=0),
                name="inventory_item_minimum_not_negative_ck",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class InventoryLot(TenantScopedModel):
    """Partia pozycji: numer z opakowania i data ważności.

    Stan partii w miejscu to suma jej ruchów — osobnej tabeli stanów nie ma, więc
    stan pozycji, rezerwacje i wszystko, co z niego czyta, zostają bez zmian.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="lots")
    number = models.CharField(max_length=64)
    #: Pusta: partia bez terminu ważności.
    expires_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "item_id", "expires_on", "number")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "item", "number"], name="inventory_lot_number_uq"
            ),
        ]

    def __str__(self) -> str:
        return self.number


class StockDocument(TenantScopedModel):
    """Dokument magazynowy. Szkic można zmieniać; zatwierdzony jest księgą.

    `source` i `source_reference` wiążą dokument z tym, co go wywołało w innym
    module (wpis korekcji, wizyta, zamówienie) — powtórka tego samego źródła nie
    tworzy drugiego dokumentu. `corrects` wskazuje dokument, który ten cofa.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    kind = models.CharField(max_length=3, choices=DocumentKind)
    status = models.CharField(max_length=8, choices=DocumentStatus, default=DocumentStatus.DRAFT)
    #: `RODZAJ/RRRR/NNNN`, nadawany przy zatwierdzeniu.
    number = models.CharField(max_length=32, blank=True)
    document_date = models.DateField()
    source_location = models.ForeignKey(
        StockLocation, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    target_location = models.ForeignKey(
        StockLocation, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="documents", null=True, blank=True
    )
    #: Odbiorca wydania zewnętrznego, dopóki klient nie jest osobnym bytem.
    counterparty = models.CharField(max_length=160, blank=True)
    corrects = models.OneToOneField(
        "self", on_delete=models.PROTECT, related_name="correction", null=True, blank=True
    )
    source = models.CharField(max_length=40, blank=True)
    source_reference = models.CharField(max_length=64, blank=True)
    note = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "-document_date", "-created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "number"],
                condition=~models.Q(number=""),
                name="inventory_document_number_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "kind", "source", "source_reference"],
                condition=~models.Q(source="") & models.Q(corrects__isnull=True),
                name="inventory_document_source_uq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "kind", "status"], name="inventory_document_kind_idx"
            ),
        ]

    def __str__(self) -> str:
        return self.number or f"{self.kind} (szkic)"


class StockDocumentLine(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    document = models.ForeignKey(StockDocument, on_delete=models.CASCADE, related_name="lines")
    position = models.PositiveSmallIntegerField()
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="+")
    #: Ilość dodatnia; przy inwentaryzacji — ilość policzona.
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    #: Cena jednostkowa w groszach: zakupu przy PZ/PW, sprzedaży przy WZ.
    unit_price_minor = models.PositiveIntegerField(null=True, blank=True)
    #: Partia przyjęta albo wskazana do rozchodu; rozchód bez niej bierze partie
    #: wg ważności, a to, co zeszło, mówią ruchy.
    lot = models.ForeignKey(
        InventoryLot, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    note = models.CharField(max_length=240, blank=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("document_id", "position")
        constraints = [
            models.UniqueConstraint(
                fields=["document", "position"], name="inventory_line_position_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0), name="inventory_line_quantity_ck"
            ),
        ]


class DocumentSequence(TenantScopedModel):
    """Ostatni numer dokumentu danego rodzaju w roku — numeracja bez dziur."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    kind = models.CharField(max_length=3, choices=DocumentKind)
    year = models.PositiveSmallIntegerField()
    last = models.PositiveIntegerField(default=0)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "kind", "year"], name="inventory_sequence_uq"
            ),
        ]


class InventoryBalance(TenantScopedModel):
    """Ile czego leży w jednym miejscu i ile z tego jest już zarezerwowane."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="balances")
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="balances")
    #: Może zejść poniżej zera: praca nie stoi przez stan, a ujemna wartość jest
    #: tym, co właściciel ma wyjaśnić (decyzja z 21.09).
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    reserved = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "item_id", "location_id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "item", "location"], name="inventory_balance_location_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(reserved__gte=0), name="inventory_balance_reserved_ck"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.item_id}@{self.location_id}: {self.quantity}"


class InventoryMovement(TenantScopedModel):
    """Jeden ruch księgi: powstaje z wiersza zatwierdzonego dokumentu i nie znika."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="movements")
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="movements")
    document = models.ForeignKey(StockDocument, on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField(max_length=3, choices=DocumentKind)
    #: Dodatnia przybywa, ujemna ubywa.
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    #: Cena jednostkowa w groszach z chwili ruchu, żeby koszt się nie zmieniał później.
    unit_cost_minor = models.PositiveIntegerField(default=0)
    #: Partia pozycji z partiami; pusta, gdy żadnej nie było (stan poniżej zera).
    lot = models.ForeignKey(
        InventoryLot, on_delete=models.PROTECT, related_name="movements", null=True, blank=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "-created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(quantity=0), name="inventory_movement_quantity_ck"
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "item"], name="inventory_movement_item_idx"),
            models.Index(fields=["organization", "location"], name="inventory_movement_place_idx"),
            models.Index(
                fields=["organization", "item", "location"], name="inventory_movement_stock_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.quantity} × {self.item_id}"


class StockReservation(TenantScopedModel):
    """Towar odłożony dla źródła (wizyty, zamówienia) — schodzi dopiero przy użyciu."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="+")
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    source = models.CharField(max_length=40)
    source_reference = models.CharField(max_length=64)
    status = models.CharField(
        max_length=10, choices=ReservationStatus, default=ReservationStatus.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "source", "source_reference", "item", "location"],
                name="inventory_reservation_source_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="inventory_reservation_quantity_ck"
            ),
        ]
