import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import polishMessages from "../../../../messages/pl.json";
import { readCsv } from "./import-sheet";
import { InventoryPanel } from "./inventory-panel";

vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const { api } = vi.hoisted(() => ({
  api: {
    listInventoryItems: vi.fn(),
    listInventoryCategories: vi.fn(),
    listStockLocations: vi.fn(),
    listSuppliers: vi.fn(),
    listMemberships: vi.fn(),
    previewInventoryImport: vi.fn(),
    applyInventoryImport: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

function result(rows: object[], invalid: number) {
  return {
    applied: false,
    replayed: false,
    summary: {
      rows: rows.length,
      created: rows.length - invalid,
      updated: 0,
      unchanged: 0,
      invalid,
      stock_lines: 1,
      new_categories: ["Chemia"],
    },
    columns: ["name", "unit", "quantity"],
    unknown_columns: ["Kolor"],
    delimiter: ";",
    location_id: "0192f000-0000-7000-8000-0000000000d1",
    document: null,
    rows,
  };
}

const good = {
  line: 2,
  action: "create",
  name: "Rękawiczki",
  sku: "REK-M",
  item_id: null,
  changes: ["name", "unit"],
  quantity: "40.000",
  problems: [],
  warnings: [
    {
      field: "name",
      code: "formula_like",
      message: "Zaczyna się jak formuła.",
    },
  ],
};
const bad = {
  ...good,
  line: 3,
  action: "error",
  name: "Bandaż",
  sku: "",
  quantity: null,
  problems: [{ field: "unit", code: "invalid_unit", message: "Nieznana." }],
  warnings: [],
};

beforeEach(() => {
  vi.resetAllMocks();
  api.listInventoryItems.mockResolvedValue([]);
  api.listInventoryCategories.mockResolvedValue([]);
  api.listSuppliers.mockResolvedValue([]);
  api.listMemberships.mockResolvedValue([]);
  api.listStockLocations.mockResolvedValue([]);
});

function renderCatalogue() {
  return render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <InventoryPanel canManage canRead section="items" />
    </NextIntlClientProvider>,
  );
}

async function chooseFile(content: BlobPart) {
  fireEvent.click(
    await screen.findByRole("button", { name: "Importuj z CSV" }),
  );
  fireEvent.change(await screen.findByLabelText("Plik CSV"), {
    target: {
      files: [new File([content], "magazyn.csv", { type: "text/csv" })],
    },
  });
}

test("plik z arkusza w Windows-1250 czyta się z polskimi literami", async () => {
  // „Rękawiczki;żółte” as an older Excel saves it.
  const bytes = new Uint8Array([
    0x52, 0xea, 0x6b, 0x61, 0x77, 0x69, 0x63, 0x7a, 0x6b, 0x69, 0x3b, 0xbf,
    0xf3, 0xb3, 0x74, 0x65,
  ]);
  expect(await readCsv(new File([bytes], "a.csv"))).toBe("Rękawiczki;żółte");
  expect(await readCsv(new File(["Rękawiczki;żółte"], "b.csv"))).toBe(
    "Rękawiczki;żółte",
  );
});

test("wiersz z błędem blokuje zapis i mówi, która komórka", async () => {
  api.previewInventoryImport.mockResolvedValue(result([good, bad], 1));
  renderCatalogue();
  await chooseFile(
    "nazwa;jednostka;ilość\nRękawiczki;opak.;40\nBandaż;wiadro;\n",
  );

  expect(
    await screen.findByText(
      "Jednostka: nieznana jednostka — np. szt., opak., ml, kg",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      "Nazwa: zaczyna się jak formuła arkusza — zapiszę to jako zwykły tekst",
    ),
  ).toBeInTheDocument();
  expect(screen.getByText(/1 wiersz ma błąd/)).toBeInTheDocument();
  expect(
    screen.getByText("Pominięte kolumny, których nie znam: Kolor."),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Zapisz" })).toBeDisabled();
  expect(api.previewInventoryImport).toHaveBeenCalledWith({
    content: "nazwa;jednostka;ilość\nRękawiczki;opak.;40\nBandaż;wiadro;\n",
    location_id: null,
  });
  expect(api.applyInventoryImport).not.toHaveBeenCalled();
});

test("poprawny plik zapisuje się jednym poleceniem z kluczem", async () => {
  api.previewInventoryImport.mockResolvedValue(result([good], 0));
  api.applyInventoryImport.mockResolvedValue({
    ...result([good], 0),
    applied: true,
  });
  renderCatalogue();
  await chooseFile("nazwa\nRękawiczki\n");

  fireEvent.click(
    await screen.findByRole("button", { name: "Zapisz 1 pozycję" }),
  );
  await waitFor(() =>
    expect(api.applyInventoryImport).toHaveBeenCalledWith(
      { content: "nazwa\nRękawiczki\n", location_id: null },
      expect.stringMatching(/^[0-9a-f-]{36}$/),
    ),
  );
  expect(
    await screen.findByText(
      "Import zapisany: nowych pozycji 1, zmienionych 0.",
    ),
  ).toBeInTheDocument();
});
