"""What a company sets for its warehouse (ADR-078; settings plan M3–M6;
warehouse plan phase 10).

Three groups on core's settings registry, in the „Magazyn” area of Ustawienia:

- `inventory.alerts` — the daily notice of what is at or below its minimum:
  off until the company switches it on (today nothing is sent; coordinator's
  decision 03.10), which places it watches, who hears and from what hour of
  the company's day. The minimum itself is data — an item's, or one place's
  over it (`InventoryBalance.minimum_quantity`) — not a setting.
- `inventory.lots` — how many days before its date a lot counts as expiring
  (a category may say otherwise: `InventoryCategory.expiring_days`), and
  whether a sale (WZ) of an expired lot is refused or only warned about. At
  work an expired lot only warns, always: recording what was done is never
  stopped (decisions 21.09 and 25.09) — a constant with its reason, not a
  setting.
- `inventory.materials` (M5) — whether a calendar visit's products come from
  the main warehouse or from the stock of the person leading it. The
  warehouse chooses the place (`visit_place`); booking only asks.
"""

from __future__ import annotations

from saas_core.modules.core.organizations.api import (
    SettingArea,
    SettingGroup,
    SettingSpec,
    group_commands,
    register_command,
    register_setting_area,
    register_setting_group,
)

from .permissions import INVENTORY_MANAGE

INVENTORY_ENABLED = "inventory.enabled"

LOW_STOCK = "inventory.alerts.low_stock"
PLACES = "inventory.alerts.places"
RECIPIENTS = "inventory.alerts.recipients"
HOLDER = "inventory.alerts.holder"
HOUR = "inventory.alerts.hour"
EXPIRING_DAYS = "inventory.lots.expiring_days"
EXPIRED_SALE = "inventory.lots.expired_sale"
MATERIALS_SOURCE = "inventory.materials.source"

#: The code's value of `inventory.lots.expiring_days` (decision 25.09).
DEFAULT_EXPIRING_DAYS = 30

AREA = SettingArea(
    key="inventory",
    title={"pl": "Magazyn", "en": "Warehouse"},
    description={
        "pl": "Powiadomienia o małym stanie i ważność partii. Towary, magazyny i dostawcy są w "
        "Magazynie.",
        "en": "Low-stock notices and lot expiry. Items, warehouses and suppliers live in "
        "the Warehouse.",
    },
    order=55,
)

ALERTS = SettingGroup(
    key="inventory.alerts",
    module="shared.inventory",
    title={"pl": "Powiadomienia o małym stanie", "en": "Low-stock notices"},
    description={
        "pl": "Raz dziennie lista tego, czego jest tyle co minimum albo mniej — w panelu i "
        "e-mailem. Minimum ustawia się przy pozycji w Katalogu albo przy miejscu w Stanach.",
        "en": "Once a day, a list of what is at or below its minimum — in the panel and by "
        "e-mail. The minimum is set on the item in the Catalogue or on a place in Stock.",
    },
    permission=INVENTORY_MANAGE,
    entitlement=INVENTORY_ENABLED,
    area="inventory",
    settings=(
        SettingSpec(
            key=LOW_STOCK,
            type="enum",
            default="off",
            scopes=("organization",),
            values=(
                ("off", {"pl": "Nie wysyłaj", "en": "Don't send"}),
                ("daily", {"pl": "Codziennie", "en": "Daily"}),
            ),
            label={"pl": "Powiadomienie o małym stanie", "en": "Low-stock notice"},
            help={
                "pl": "Codziennie: jedna wiadomość dziennie, dopóki coś jest na minimum lub "
                "poniżej. Nic nie brakuje — nic nie przychodzi.",
                "en": "Daily: one message a day while anything is at or below its minimum. "
                "Nothing short — nothing sent.",
            },
            model_description="Whether the company gets a daily notice (in the panel and by "
            "e-mail) listing the items whose available stock is at or below their minimum. "
            "Off by default: nothing is sent until the company switches it on.",
        ),
        SettingSpec(
            key=PLACES,
            type="enum",
            default="main",
            scopes=("organization",),
            depends_on="low_stock == 'daily'",
            values=(
                ("main", {"pl": "Magazyn główny", "en": "The main warehouse"}),
                ("warehouses", {"pl": "Wszystkie magazyny", "en": "All warehouses"}),
                (
                    "all",
                    {
                        "pl": "Magazyny i zapasy osób",
                        "en": "Warehouses and people's stock",
                    },
                ),
            ),
            label={"pl": "Sprawdzaj", "en": "Watch"},
            help={
                "pl": "Zapas osoby ma tylko minimum ustawione przy nim w Stanach — minimum "
                "pozycji dotyczy magazynów.",
                "en": "A person's stock has only the minimum set on it in Stock — an item's "
                "minimum is for warehouses.",
            },
            model_description="Which places the notice watches: the main warehouse, every "
            "warehouse of the company, or warehouses and people's own stock. The minimum in "
            "force in a place is resolved by the warehouse itself, not by this setting: the "
            "minimum set on that place (PUT /inventory/minimums/; 0 = none there), else — in "
            "a warehouse — the item's minimum; a person's stock has only its own.",
        ),
        SettingSpec(
            key=RECIPIENTS,
            type="enum",
            default="managers",
            scopes=("organization",),
            depends_on="low_stock == 'daily'",
            values=(
                (
                    "managers",
                    {
                        "pl": "Każdy, kto prowadzi magazyn",
                        "en": "Everyone who runs the warehouse",
                    },
                ),
                ("owner", {"pl": "Tylko właściciel", "en": "The owner only"}),
            ),
            label={"pl": "Kto dostaje", "en": "Who gets it"},
            model_description="Who gets the notice: everyone whose role may run the warehouse "
            "(inventory.manage), or only the company's owner.",
        ),
        SettingSpec(
            key=HOLDER,
            type="bool",
            default=True,
            scopes=("organization",),
            depends_on="places == 'all'",
            label={
                "pl": "Osoba dostaje też o swoim zapasie",
                "en": "A person also hears about their own stock",
            },
            help={
                "pl": "Np. serwisant albo korektor dowie się, że w jego pakiecie kończy się "
                "materiał.",
                "en": "E.g. a technician learns that something in their kit is running out.",
            },
            model_description="With people's stock watched: the person whose own stock is at "
            "or below its minimum also gets a notice about it (only their own rows).",
        ),
        SettingSpec(
            key=HOUR,
            type="int",
            minimum=0,
            maximum=23,
            default=7,
            scopes=("organization",),
            depends_on="low_stock == 'daily'",
            label={"pl": "Od godziny (czas firmy)", "en": "From the hour (company time)"},
            help={
                "pl": "Wiadomość wychodzi raz dziennie, pierwszy raz od tej godziny, gdy coś "
                "jest na minimum lub poniżej.",
                "en": "The message goes out once a day, the first time from this hour that "
                "anything is at or below its minimum.",
            },
            model_description="The hour of the company's day (0 to 23, its time zone) from "
            "which the daily notice may go out; it goes once a day, the first time something "
            "is at or below its minimum at or after this hour.",
        ),
    ),
    commands=("inventory.settings_alerts.read@1", "inventory.settings_alerts.update@1"),
)

LOTS = SettingGroup(
    key="inventory.lots",
    module="shared.inventory",
    title={"pl": "Ważność partii", "en": "Lot expiry"},
    description={
        "pl": "Dotyczy pozycji z partiami i datami ważności. W pracy partia po terminie tylko "
        "ostrzega — zapisu nigdy nie blokuje.",
        "en": "For items kept by lots and expiry dates. At work an expired lot only warns — "
        "it never stops a record.",
    },
    permission=INVENTORY_MANAGE,
    entitlement=INVENTORY_ENABLED,
    area="inventory",
    settings=(
        SettingSpec(
            key=EXPIRING_DAYS,
            type="int",
            minimum=1,
            maximum=365,
            unit="day",
            default=DEFAULT_EXPIRING_DAYS,
            scopes=("organization",),
            label={
                "pl": "„Kończy się ważność” na tyle dni przed terminem",
                "en": "„Expiring” this many days before the date",
            },
            help={
                "pl": "Kategoria może mieć własną liczbę dni (Magazyn › Ustawienia › Kategorie).",
                "en": "A category may have its own number of days (Warehouse › Settings › "
                "Categories).",
            },
            model_description="How many days before its expiry date a lot is shown as "
            "expiring (1 to 365). A category's own number (`expiring_days` on the category, "
            "PATCH /inventory/categories/{id}/) wins over this one.",
        ),
        SettingSpec(
            key=EXPIRED_SALE,
            type="enum",
            default="block",
            scopes=("organization",),
            values=(
                ("block", {"pl": "Odmów sprzedaży", "en": "Refuse the sale"}),
                ("warn", {"pl": "Tylko ostrzegaj", "en": "Warn only"}),
            ),
            label={
                "pl": "Sprzedaż (WZ) partii po terminie",
                "en": "A sale (WZ) of an expired lot",
            },
            model_description="What a sale to a customer (WZ posted in the panel) does with a "
            "lot past its date: refuse it (default, as before), or let it go after the valid "
            "lots with the lot's status shown. Work (consumption at a visit, in the field) is "
            "never stopped by an expired lot and has no setting: recording what was done is "
            "never blocked (owner decisions 21.09 and 25.09).",
        ),
    ),
    commands=("inventory.settings_lots.read@1", "inventory.settings_lots.update@1"),
)


MATERIALS = SettingGroup(
    key="inventory.materials",
    module="shared.inventory",
    title={"pl": "Materiały przy wizytach", "en": "Materials at visits"},
    description={
        "pl": "Skąd schodzą produkty wpisane do wizyty w kalendarzu: rezerwacja od potwierdzenia, "
        "zużycie i sprzedaż przy zakończeniu.",
        "en": "Where the products on a calendar visit come from: reserved from confirmation, "
        "used and sold when it is completed.",
    },
    permission=INVENTORY_MANAGE,
    entitlement=INVENTORY_ENABLED,
    area="inventory",
    settings=(
        SettingSpec(
            key=MATERIALS_SOURCE,
            type="enum",
            default="main",
            scopes=("organization",),
            values=(
                ("main", {"pl": "Magazyn główny", "en": "The main warehouse"}),
                (
                    "lead_person",
                    {
                        "pl": "Zapas osoby prowadzącej wizytę",
                        "en": "The stock of the person leading the visit",
                    },
                ),
            ),
            label={"pl": "Produkty wizyty biorę z", "en": "A visit's products come from"},
            help={
                "pl": "Zapas osoby: np. serwisant z busem. Osoba bez konta w panelu nie ma "
                "zapasu — wtedy magazyn główny.",
                "en": "A person's stock: e.g. a technician with a van. A person without a panel "
                "account has no stock — then the main warehouse.",
            },
            model_description="Where the products of a calendar visit are reserved and taken "
            "from: the main warehouse (default, as before) or the own stock of the person "
            "leading the visit (the main warehouse when that person has no account). Visits "
            "whose module accounts for its own material (HoofCare's) are not affected.",
        ),
    ),
    commands=("inventory.settings_materials.read@1", "inventory.settings_materials.update@1"),
)


def register_company_settings() -> None:
    register_setting_area(AREA)
    for group in (ALERTS, LOTS, MATERIALS):
        register_setting_group(group)
        for command in group_commands(group):
            register_command(command)
