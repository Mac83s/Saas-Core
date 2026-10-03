"""The catalogue from a CSV (phase 10c): a preview that writes nothing, a save
that writes everything or nothing, and a file that is read, never kept."""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any

import pytest
from django.conf import settings
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.models import Membership, OrganizationAuditEntry
from test_inventory import (
    core_catalog,  # noqa: F401 — core's own catalogue, not a product's
    item,
    membership,
    quantities,
    tenant,
)
from test_inventory_alerts import member

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        "shared.inventory" not in settings.ACTIVE_MODULES,
        reason="magazyn istnieje tylko w profilu, który go składa",
    ),
]

HEADER = (
    "nazwa;sku;kategoria;jednostka;stan minimalny;cena sprzedaży netto;vat;partie;"
    "ilość;cena zakupu;partia;ważność"
)
FILE = f"""{HEADER}
Rękawiczki nitrylowe M;REK-M;Materiał;opak.;5;39,00;23;nie;40;18,90;;
Płyn do dezynfekcji;DEZ-1;Chemia;l;2;;8%;tak;12,5;31,20;L-77;31.12.2027
Klocek;;;szt.;10;;;;;;;
"""


def run(request: Any, content: str, **options: Any) -> dict[str, Any]:
    from saas_core.modules.shared.inventory.imports import import_items  # noqa: PLC0415

    return import_items(request=request, content=content, **options)


def catalogue(owner: Membership) -> dict[str, Any]:
    from saas_core.modules.shared.inventory.models import InventoryItem  # noqa: PLC0415

    return {
        one.name: one
        for one in InventoryItem.all_objects.filter(
            organization_id=owner.organization_id
        ).select_related("category")
    }


def test_the_template_is_a_file_the_import_reads_and_holds_no_formula() -> None:
    from saas_core.modules.shared.inventory.imports import (  # noqa: PLC0415
        COLUMNS,
        FORMULA_START,
        MAX_IMPORT_BYTES,
        MAX_IMPORT_ROWS,
        template,
    )

    sheet = template()
    assert (sheet["max_rows"], sheet["max_bytes"]) == (MAX_IMPORT_ROWS, MAX_IMPORT_BYTES)
    header, example = list(csv.reader(io.StringIO(sheet["csv"]), delimiter=";"))
    assert header == [column.headers[0] for column in COLUMNS]
    for cell in (*header, *example):
        assert not cell.startswith(FORMULA_START)
    assert [column["key"] for column in sheet["columns"] if column["mandatory"]] == ["name"]


def test_a_preview_says_what_a_save_would_do_and_writes_nothing() -> None:
    owner = membership("import-podglad")
    with tenant(owner) as request:
        item(request, "Klocek")
        before = set(catalogue(owner))
        result = run(request, FILE, preview=True)
        assert set(catalogue(owner)) == before
        assert not OrganizationAuditEntry.objects.filter(
            organization_id=owner.organization_id, action="inventory.imported"
        ).exists()
    assert (result["applied"], result["document"]) == (False, None)
    assert result["summary"] == {
        "rows": 3,
        "created": 2,
        "updated": 1,
        "unchanged": 0,
        "invalid": 0,
        "stock_lines": 2,
        "new_categories": ["Chemia"],
    }
    assert result["delimiter"] == ";"
    assert [(row["line"], row["action"]) for row in result["rows"]] == [
        (2, "create"),
        (3, "create"),
        (4, "update"),
    ]
    # The existing „Klocek” only gets its minimum (the unit is already a piece).
    assert result["rows"][2]["changes"] == ["minimum_quantity"]


def test_a_save_creates_items_changes_existing_ones_and_receives_the_opening_stock() -> None:
    from saas_core.modules.shared.inventory.services import (  # noqa: PLC0415
        create_warehouse,
        list_lots,
        update_item,
    )

    owner = membership("import-zapis")
    with tenant(owner) as request:
        block = item(request, "Klocek")
        update_item(request=request, item_id=block.id, data={"sku": "KL-1"})
        branch = create_warehouse(request=request, name="Oddział")
        result = run(request, FILE, location_id=branch.id, idempotency_key="import-1")
        assert result["applied"] and result["document"]["number"].startswith("PW/")
        items = catalogue(owner)
        gloves, liquid = items["Rękawiczki nitrylowe M"], items["Płyn do dezynfekcji"]
        assert (gloves.sku, gloves.unit, gloves.category.name) == ("REK-M", "pack", "Materiał")
        assert (gloves.minimum_quantity, gloves.sale_price_net_minor) == (Decimal(5), 3900)
        # The purchase price of the stock received is the item's average cost.
        assert (gloves.average_cost_minor, liquid.average_cost_minor) == (1890, 3120)
        assert (liquid.vat_rate, liquid.tracks_lots, liquid.category.name) == ("8", True, "Chemia")
        assert liquid.category.system is False
        assert (items["Klocek"].minimum_quantity, items["Klocek"].sku) == (Decimal(10), "KL-1")
        assert quantities(location_id=branch.id) == {
            "Rękawiczki nitrylowe M": Decimal(40),
            "Płyn do dezynfekcji": Decimal("12.5"),
        }
        (lot,) = list_lots()
        assert (lot["number"], str(lot["expires_on"])) == ("L-77", "2027-12-31")

        (entry,) = OrganizationAuditEntry.objects.filter(
            organization_id=owner.organization_id, action="inventory.imported"
        )
        assert (entry.metadata["created"], entry.metadata["updated"]) == (2, 1)
        # The file is read, never kept: counts and a hash, not its rows.
        assert "Rękawiczki" not in str(entry.metadata)
        assert len(entry.metadata["content_sha256"]) == 64

        # The same key again: the first answer, and the stock is not received twice.
        again = run(request, FILE, location_id=branch.id, idempotency_key="import-1")
        assert (again["replayed"], again["summary"]) == (True, result["summary"])
        assert quantities(location_id=branch.id)["Rękawiczki nitrylowe M"] == Decimal(40)
        from saas_core.modules.shared.inventory.imports import (  # noqa: PLC0415
            ImportIdempotencyConflict,
        )

        with pytest.raises(ImportIdempotencyConflict):
            run(request, FILE + "Nowa;;;;;;;;;;;\n", idempotency_key="import-1")

        # A second file matches by SKU and may rename the item.
        renamed = run(
            request,
            "name,sku\nKlocek drewniany,KL-1\n",
            idempotency_key="import-2",
        )
        assert renamed["delimiter"] == ","
        assert renamed["rows"][0]["changes"] == ["name"]
        assert "Klocek drewniany" in catalogue(owner)


def test_a_wrong_row_saves_nothing_and_says_which_cell() -> None:
    owner = membership("import-bledy")
    content = (
        "nazwa;jednostka;ilość;vat;partie;ważność\n"
        "Bandaż;wiadro;5;23;nie;\n"
        ";szt.;1;;;\n"
        "Maść;szt.;-2;7;może;31-12-2027\n"
        "Bandaż;szt.;1;;;\n"
        "Dobry wiersz;szt.;1;;;\n"
    )
    with tenant(owner) as request:
        preview = run(request, content, preview=True)
        problems = {
            (row["line"], problem["field"], problem["code"])
            for row in preview["rows"]
            for problem in row["problems"]
        }
        assert problems == {
            (2, "unit", "invalid_unit"),
            (3, "name", "required"),
            (4, "quantity", "invalid_number"),
            (4, "vat_rate", "invalid_vat"),
            (4, "tracks_lots", "invalid_yes_no"),
            (4, "expires_on", "invalid_date"),
            (5, "name", "duplicate_in_file"),
        }
        assert preview["summary"]["invalid"] == 4
        with pytest.raises(ValidationError) as refused:
            run(request, content, idempotency_key="import-bad")
        assert refused.value.get_codes()["rows[2].unit"] == ["invalid_unit"]
        assert catalogue(owner) == {}
        # A lot is required where the item keeps lots, and refused where it does not.
        lots = run(
            request,
            "nazwa;partie;ilość;partia\nLek;tak;3;\nGaza;nie;3;L-1\n",
            preview=True,
        )
        assert [[p["code"] for p in row["problems"]] for row in lots["rows"]] == [
            ["lot_required"],
            ["lots_not_tracked"],
        ]


def test_a_cell_that_starts_like_a_formula_is_text_and_the_preview_flags_it() -> None:
    owner = membership("import-formuly")
    content = (
        "nazwa;sku;uwagi\n"
        '"=HYPERLINK(""http://zly.example"";""Klik"")";+48123;@SUM(A1)\n'
        "-20% rabat;OK-1;zwykła uwaga\n"
    )
    with tenant(owner) as request:
        preview = run(request, content, preview=True)
        flagged = {
            (row["line"], warning["field"])
            for row in preview["rows"]
            for warning in row["warnings"]
            if warning["code"] == "formula_like"
        }
        assert flagged == {(2, "name"), (2, "sku"), (2, "notes"), (3, "name")}
        assert preview["summary"]["invalid"] == 0
        run(request, content, idempotency_key="import-formula")
        saved = catalogue(owner)
        # Kept as the text it is — never evaluated, never rewritten.
        formula = saved['=HYPERLINK("http://zly.example";"Klik")']
        assert (formula.sku, formula.notes) == ("+48123", "@SUM(A1)")
        assert "-20% rabat" in saved


def test_the_limits_the_header_and_who_may_import() -> None:
    from saas_core.modules.shared.inventory import imports  # noqa: PLC0415

    owner = membership("import-limity")
    worker = member(owner, "import-pracownik", "staff")
    with tenant(owner) as request:
        for content, code in (
            ("", "empty"),
            ("sku;jednostka\nA;szt.\n", "missing_name_column"),
            ("nazwa;nazwa\nA;B\n", "duplicate_column"),
            ("nazwa\n" + "x\n" * (imports.MAX_IMPORT_ROWS + 1), "too_many_rows"),
            ("nazwa\n" + "y" * imports.MAX_IMPORT_BYTES, "file_too_large"),
        ):
            with pytest.raises(ValidationError) as refused:
                run(request, content, preview=True)
            assert refused.value.get_codes() == {"content": [code]}, code
        # A column the import does not know is named and ignored; a BOM is not a name.
        result = run(request, "﻿Nazwa;Kolor\nKlocek;czerwony\n", preview=True)
        assert (result["columns"], result["unknown_columns"]) == (["name"], ["Kolor"])
        with pytest.raises(ValidationError) as keyless:
            run(request, "nazwa\nKlocek\n")
        assert keyless.value.get_codes() == {"idempotency_key": ["required"]}
        # Opening stock goes to a warehouse, not to somebody's kit.
        from saas_core.modules.shared.inventory.api import person_location  # noqa: PLC0415

        kit = person_location(owner.organization_id, worker.user_id)
        with pytest.raises(ValidationError) as place:
            run(request, "nazwa\nKlocek\n", location_id=kit.id, preview=True)
        assert place.value.get_codes() == {"location_id": ["invalid"]}
    with tenant(worker) as request, pytest.raises(OrganizationPermissionDenied):
        run(request, "nazwa\nKlocek\n", preview=True)
