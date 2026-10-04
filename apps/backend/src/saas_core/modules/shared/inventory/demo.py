"""The warehouse's part of the demo (core/organizations/demo.py).

For every organization whose scenario data has `inventory`: catalogue items, a
receipt (PZ) into the main warehouse — with lots and expiry dates where an item
tracks them — then, per person, what they were given (MM to their stock), what
they used (RW from it) and what they gave back (MM to the warehouse). The
Warehouse tab then has stock and movements, and a person's card its numbers
(inventory/facts.py).

Documents get ids that are the same on every run, so a second run finds them
posted and changes nothing; items are found by name. Data shape:

    {"items": [{"name", "unit", "sku", "category", "cost_minor", "tracks_lots",
                "lots": [{"number", "expires_in_days", "quantity"}] | "quantity"}],
     "issue": {email: {item: qty}}, "use": {email: {item: qty}},
     "return": {email: {item: qty}}}
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from .models import InventoryCategory, InventoryItem, StockDocument
from .services import (
    LineInput,
    create_document,
    create_item,
    default_warehouse,
    person_location,
    post_document,
)

if TYPE_CHECKING:
    from saas_core.modules.core.organizations.demo import DemoRequest, DemoRun

BUSINESS: dict[str, Any] = {
    "items": [
        {
            "name": "Papier do drukarki A4 (ryza)",
            "unit": "pack",
            "sku": "DEMO-A4",
            "category": "other",
            "cost_minor": 2490,
            "quantity": 20,
        },  # noqa: E501
        {
            "name": "Tusz do drukarki — czarny",
            "unit": "piece",
            "sku": "DEMO-INK",
            "category": "other",
            "cost_minor": 8900,
            "quantity": 6,
        },  # noqa: E501
        {
            "name": "Płyn do dezynfekcji 1 l",
            "unit": "piece",
            "sku": "DEMO-DEZ",
            "category": "material",
            "cost_minor": 1990,
            "quantity": 12,  # noqa: E501
            "tracks_lots": True,
            "lots": [{"number": "DZ-2409", "expires_in_days": 120, "quantity": 12}],
        },  # noqa: E501
        {
            "name": "Rękawiczki nitrylowe M (100 szt.)",
            "unit": "pack",
            "sku": "DEMO-GLV",
            "category": "material",
            "cost_minor": 2990,
            "quantity": 10,
        },  # noqa: E501
    ],
    "issue": {
        "pracownik@saas.test": {
            "Rękawiczki nitrylowe M (100 szt.)": 2,
            "Płyn do dezynfekcji 1 l": 2,
        },
        "kierownik@saas.test": {"Papier do drukarki A4 (ryza)": 4},
    },
    "use": {
        "pracownik@saas.test": {
            "Rękawiczki nitrylowe M (100 szt.)": 1,
            "Płyn do dezynfekcji 1 l": 1,
        }
    },  # noqa: E501
    "return": {"kierownik@saas.test": {"Papier do drukarki A4 (ryza)": 1}},
}


def seed_warehouse(run: DemoRun) -> None:
    for spec in run.scenario.organizations:
        data = run.data(spec.key, "inventory")
        if data is None and run.scenario.default and spec.key == "studio":
            data = BUSINESS
        if data is not None:
            with run.acting(spec.key) as request:
                _seed_organization(run, spec.key, data, request)


def _seed_organization(run: DemoRun, key: str, data: dict[str, Any], request: DemoRequest) -> None:
    organization = run.organizations[key]
    warehouse = default_warehouse(organization.id)
    items: dict[str, InventoryItem] = {}
    for wanted in data["items"]:
        item = InventoryItem.all_objects.filter(
            organization_id=organization.id, name__iexact=wanted["name"]
        ).first()
        if item is None:
            # A category key of the organization's type (ensure_catalog). A
            # product's type need not have the core's keys ("material" is not a
            # hoof trimmer's): the item then goes without a category.
            category = wanted.get("category", "")
            if (
                category
                and not InventoryCategory.all_objects.filter(
                    organization_id=organization.id, key=category
                ).exists()
            ):
                category = ""
            item = create_item(
                request=request,
                data={
                    "name": wanted["name"],
                    "sku": wanted.get("sku", ""),
                    "unit": wanted.get("unit", "piece"),
                    "tracks_lots": bool(wanted.get("tracks_lots")),
                    "category": category,
                    "minimum_quantity": Decimal(str(wanted.get("minimum", 0))),
                },
            )
            run.log(f"+ pozycja {item.name}")
        items[wanted["name"]] = item

    def document(name: str, kind: str, places: dict[str, Any], lines: list[LineInput]) -> None:
        document_id = run.stable_id(organization.slug, "inventory", name)
        if StockDocument.all_objects.filter(
            organization_id=organization.id, pk=document_id, status="posted"
        ).exists():
            return
        create_document(
            request=request,
            kind=kind,
            data={**places, "note": "Dane demo (seed_demo)"},
            lines=lines,
            document_id=document_id,
        )
        posted = post_document(request=request, document_id=document_id)
        run.log(f"+ {posted.number}")

    receipt: list[LineInput] = []
    for wanted in data["items"]:
        item = items[wanted["name"]]
        price = int(wanted.get("cost_minor", 0)) or None
        for lot in wanted.get("lots") or []:
            receipt.append(
                LineInput(
                    item_id=item.id,
                    quantity=Decimal(str(lot["quantity"])),
                    unit_price_minor=price,
                    lot_number=lot["number"],
                    expires_on=run.day(key, int(lot["expires_in_days"])),
                )
            )
        if not wanted.get("lots"):
            receipt.append(
                LineInput(
                    item_id=item.id,
                    quantity=Decimal(str(wanted.get("quantity", 1))),
                    unit_price_minor=price,
                )
            )
    document("receipt", "PZ", {"target_location_id": warehouse.id}, receipt)

    def lines(quantities: dict[str, Any]) -> list[LineInput]:
        return [
            LineInput(item_id=items[name].id, quantity=Decimal(str(quantity)))
            for name, quantity in quantities.items()
        ]

    for email, quantities in (data.get("issue") or {}).items():
        place = person_location(organization.id, run.user(email).pk)
        document(
            f"issue:{email}",
            "MM",
            {"source_location_id": warehouse.id, "target_location_id": place.id},
            lines(quantities),
        )
    for email, quantities in (data.get("use") or {}).items():
        place = person_location(organization.id, run.user(email).pk)
        document(f"use:{email}", "RW", {"source_location_id": place.id}, lines(quantities))
    for email, quantities in (data.get("return") or {}).items():
        place = person_location(organization.id, run.user(email).pk)
        document(
            f"return:{email}",
            "MM",
            {"source_location_id": place.id, "target_location_id": warehouse.id},
            lines(quantities),
        )
