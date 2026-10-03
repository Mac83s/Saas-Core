import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import polishMessages from "../../../../messages/pl.json";
import { InventoryPanel } from "./inventory-panel";

vi.mock("#i18n/navigation", () => ({ Link: "a" }));
const { search } = vi.hoisted(() => ({ search: { value: "" } }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search.value),
}));

const { api } = vi.hoisted(() => ({
  api: {
    listInventoryItems: vi.fn(),
    listInventoryCategories: vi.fn(),
    listStockLocations: vi.fn(),
    listSuppliers: vi.fn(),
    listInventoryBalances: vi.fn(),
    listMemberships: vi.fn(),
    getSettingsGroup: vi.fn(),
    setInventoryPlaceMinimum: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const WAREHOUSE = "0192f000-0000-7000-8000-0000000000d1";

function row(name: string, available: string, minimum: string | null) {
  const id = `0192f000-0000-7000-8000-${name.length.toString().padStart(12, "0")}`;
  return {
    item_id: id,
    item_name: name,
    sku: "",
    category: null,
    category_name: null,
    unit: "piece",
    location_id: WAREHOUSE,
    location_name: "Magazyn główny",
    holder_id: null,
    quantity: available,
    reserved: "0.000",
    available,
    minimum_quantity: minimum,
    place_minimum: null,
    below_minimum: minimum !== null && Number(available) <= Number(minimum),
    tracks_lots: false,
    nearest_expiry: null,
    lot_status: null,
    updated_at: "2026-10-03T08:00:00Z",
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  search.value = "";
  api.listInventoryItems.mockResolvedValue([]);
  api.listInventoryCategories.mockResolvedValue([]);
  api.listSuppliers.mockResolvedValue([]);
  api.listMemberships.mockResolvedValue([]);
  api.listStockLocations.mockResolvedValue([
    {
      id: WAREHOUSE,
      kind: "warehouse",
      name: "Magazyn główny",
      holder_id: null,
      holder_name: null,
      is_default: true,
      active: true,
    },
  ]);
  api.listInventoryBalances.mockResolvedValue([
    row("Klocek", "2.000", "5.000"),
    row("Rękawiczki", "40.000", "5.000"),
    row("Bandaż elastyczny", "3.000", null),
  ]);
  api.getSettingsGroup.mockResolvedValue({ values: { low_stock: "off" } });
  api.setInventoryPlaceMinimum.mockResolvedValue({});
});

function renderStock() {
  return render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <InventoryPanel canManage canRead section="stock" />
    </NextIntlClientProvider>,
  );
}

test("„Do uzupełnienia” zostawia to, co jest na minimum albo niżej, i podpowiada powiadomienie", async () => {
  renderStock();
  expect(await screen.findByText("Rękawiczki")).toBeInTheDocument();
  // Wyłączone domyślnie: lista sama mówi, że powiadomienie istnieje.
  const hint = await screen.findByRole("link", {
    name: "Włącz codzienne powiadomienie",
  });
  expect(hint).toHaveAttribute("href", "/panel/settings/inventory");

  fireEvent.change(screen.getByLabelText("Pokaż"), {
    target: { value: "low" },
  });
  expect(screen.getByText("Klocek")).toBeInTheDocument();
  expect(screen.queryByText("Rękawiczki")).not.toBeInTheDocument();
  expect(screen.queryByText("Bandaż elastyczny")).not.toBeInTheDocument();
});

test("link z powiadomienia otwiera listę już zawężoną, a włączone powiadomienie nie jest podpowiadane", async () => {
  search.value = "low=1";
  api.getSettingsGroup.mockResolvedValue({ values: { low_stock: "daily" } });
  renderStock();
  expect(await screen.findByText("Klocek")).toBeInTheDocument();
  expect(screen.queryByText("Rękawiczki")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Włącz codzienne powiadomienie" }),
  ).not.toBeInTheDocument();
});

test("minimum w miejscu: puste pole wraca do minimum pozycji", async () => {
  renderStock();
  expect(await screen.findByText("Bandaż elastyczny")).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Akcje: Bandaż elastyczny" }),
  );
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "Minimum w tym miejscu" }),
  );
  const field = await screen.findByLabelText("Minimum tutaj (szt.)");
  fireEvent.change(field, { target: { value: "4" } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(api.setInventoryPlaceMinimum).toHaveBeenCalledWith(
      expect.objectContaining({
        location_id: WAREHOUSE,
        minimum_quantity: "4",
      }),
    ),
  );
});
