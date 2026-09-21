"""Magazyn materiałów: co firma ma, komu to wydała i co z tego zeszło.

Jeden katalog na wszystko, czego korektor używa przy pracy — leki są w nim
kategorią, nie osobnym magazynem, bo w torbie i tak leżą obok klocków
(decyzja z 21.09). Stan trzymamy w dwóch miejscach: w magazynie firmy i w
imiennym zapasie pracownika, który wyjeżdża z pakietem i z niego się rozlicza.

Stan nie jest polem, które ktoś ustawia: wynika z ruchów. `InventoryBalance`
to wyliczona suma, którą trzymamy obok, żeby ekran w oborze nie musiał
sumować historii — a `InventoryMovement` zostaje zapisem tego, co się
naprawdę stało, i nigdy nie znika.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel


class ItemCategory(models.TextChoices):
    """Po co sięga korektor. Kategoria steruje tym, co ekran pokazuje z góry."""

    BLOCK = "block", "Klocek"
    DRESSING = "dressing", "Opatrunek"
    MEDICINE = "medicine", "Lek"
    TOOL = "tool", "Narzędzie"
    OTHER = "other", "Inne"


class ItemUnit(models.TextChoices):
    PIECE = "piece", "Sztuka"
    PACK = "pack", "Opakowanie"
    MILLILITRE = "ml", "Mililitr"
    GRAM = "g", "Gram"
    METRE = "m", "Metr"


class MovementKind(models.TextChoices):
    RECEIPT = "receipt", "Przyjęcie"
    ISSUE = "issue", "Wydanie pracownikowi"
    RETURN = "return", "Zwrot do magazynu"
    CONSUMPTION = "consumption", "Zużycie przy pracy"
    ADJUSTMENT = "adjustment", "Korekta stanu"


class InventoryItem(TenantScopedModel):
    """Pozycja katalogu: to, co firma kupuje i wydaje."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=16, choices=ItemCategory, default=ItemCategory.OTHER)
    unit = models.CharField(max_length=8, choices=ItemUnit, default=ItemUnit.PIECE)
    #: Poniżej tej wartości magazyn firmy prosi o uzupełnienie; 0 wyłącza próg.
    minimum_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    #: Średnia ważona cena zakupu, w groszach. Rozchód wycenia się po niej, bo
    #: śledzenie partii przy każdym ruchu kosztuje więcej, niż daje.
    average_cost_minor = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="PLN")
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
            models.CheckConstraint(
                condition=models.Q(minimum_quantity__gte=0),
                name="inventory_item_minimum_not_negative_ck",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class InventoryBalance(TenantScopedModel):
    """Ile czego leży w jednym miejscu: w magazynie firmy albo u człowieka.

    `holder` puste znaczy magazyn firmy. Trzymanie obu w jednej tabeli sprawia,
    że wydanie i zwrot to dwa wiersze tego samego rodzaju, a nie dwa osobne
    mechanizmy.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="balances")
    holder = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="inventory_balances",
        null=True,
        blank=True,
    )
    #: Może zejść poniżej zera: praca w oborze nie stoi przez stan magazynowy,
    #: a ujemna wartość jest tym, co właściciel ma wyjaśnić.
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "item_id", "holder_id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "item", "holder"],
                name="inventory_balance_item_holder_uq",
                nulls_distinct=False,
            )
        ]

    def __str__(self) -> str:
        return f"{self.item_id}: {self.quantity}"


class InventoryMovement(TenantScopedModel):
    """Jeden ruch: przyjęcie, wydanie, zwrot, zużycie albo korekta.

    Append-only z założenia — pomyłkę prostuje się korektą, nie kasowaniem,
    bo stan ma dać się wyprowadzić z historii. `source` i `source_reference`
    wiążą zużycie z tym, co je wywołało (wizytą, wpisem korekcji), i robią z
    ruchu coś, co da się wytłumaczyć po miesiącu.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField(max_length=16, choices=MovementKind)
    #: Dodatnia dla przyjęcia i zwrotu, ujemna dla wydania i zużycia.
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    #: Kogo dotyczy zapas: pusty to magazyn firmy.
    holder = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="inventory_movements",
        null=True,
        blank=True,
    )
    #: Cena jednostkowa w groszach: przy przyjęciu z faktury, przy rozchodzie
    #: średnia z chwili ruchu, żeby koszt wizyty nie zmieniał się później.
    unit_cost_minor = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=32, blank=True)
    source_reference = models.CharField(max_length=64, blank=True)
    note = models.CharField(max_length=240, blank=True)
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
            models.UniqueConstraint(
                fields=["organization", "source", "source_reference", "item", "holder"],
                condition=~models.Q(source=""),
                name="inventory_movement_source_uq",
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "item"], name="inventory_movement_item_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.quantity} × {self.item_id}"
