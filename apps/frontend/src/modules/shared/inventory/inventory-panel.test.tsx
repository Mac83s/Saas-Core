import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import polishMessages from "../../../../messages/pl.json";
import { InventoryPanel } from "./inventory-panel";

const { api } = vi.hoisted(() => ({
  api: {
    listInventoryItems: vi.fn(),
    listInventoryCategories: vi.fn(),
    listStockLocations: vi.fn(),
    listSuppliers: vi.fn(),
    listInventoryBalances: vi.fn(),
    listStockDocuments: vi.fn(),
    listMemberships: vi.fn(),
    issueInventory: vi.fn(),
    createStockDocument: vi.fn(),
    postStockDocument: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const BLOCK = "0192f000-0000-7000-8000-0000000000b1";
const TRIMMER = "0192f000-0000-7000-8000-0000000000c1";
const WAREHOUSE = "0192f000-0000-7000-8000-0000000000d1";
const PERSONAL = "0192f000-0000-7000-8000-0000000000d2";

const item = {
  id: BLOCK,
  name: "Klocek drewniany",
  sku: "",
  ean: "",
  category_id: null,
  category: null,
  category_name: null,
  unit: "piece",
  minimum_quantity: "5.000",
  average_cost_minor: 1250,
  sale_price_net_minor: null,
  vat_rate: "23",
  currency: "PLN",
  system_key: "block",
  active: true,
  notes: "",
};

function balance(quantity: string, location: string, holder: string | null) {
  return {
    item_id: BLOCK,
    item_name: item.name,
    sku: "",
    category: null,
    category_name: null,
    unit: "piece",
    location_id: location,
    location_name: holder ? "Zapas osoby" : "Magazyn główny",
    holder_id: holder,
    quantity,
    reserved: "0.000",
    available: quantity,
    minimum_quantity: "5.000",
    updated_at: "2026-09-21T08:00:00Z",
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  api.listInventoryItems.mockResolvedValue([item]);
  api.listInventoryCategories.mockResolvedValue([]);
  api.listSuppliers.mockResolvedValue([]);
  api.listStockDocuments.mockResolvedValue([]);
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
    {
      id: PERSONAL,
      kind: "person",
      name: "Zapas osoby",
      holder_id: TRIMMER,
      holder_name: "Piotr Korektor",
      is_default: false,
      active: true,
    },
  ]);
  api.listMemberships.mockResolvedValue([
    {
      id: "0192f000-0000-7000-8000-0000000000c9",
      user_id: TRIMMER,
      email: "piotr@example.test",
      first_name: "Piotr",
      last_name: "Korektor",
      role: "trimmer",
      status: "active",
      joined_at: "2026-09-01T08:00:00Z",
    },
  ]);
  api.issueInventory.mockResolvedValue({});
});

function renderPanel(props: { canManage?: boolean } = { canManage: true }) {
  return render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <InventoryPanel canRead {...props} />
    </NextIntlClientProvider>,
  );
}

test("wydanie osobie pokazuje, co ma przy sobie, i idzie jako jedno polecenie", async () => {
  // Magazyn główny, zapas wskazanej osoby — dwa różne pytania.
  api.listInventoryBalances.mockImplementation(
    (query?: { locationId?: string; holderId?: string }) =>
      Promise.resolve(
        query?.holderId
          ? [balance("2.000", PERSONAL, TRIMMER)]
          : [balance("20.000", WAREHOUSE, null)],
      ),
  );

  renderPanel();
  expect(await screen.findByText("Klocek drewniany")).toBeInTheDocument();
  expect(api.listInventoryBalances).toHaveBeenCalledWith({
    locationId: WAREHOUSE,
  });

  fireEvent.click(screen.getByRole("button", { name: "Wydaj osobie" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Osoba"), {
    target: { value: TRIMMER },
  });
  // Dopiero po wskazaniu osoby widać, z czym ona już jeździ.
  expect(
    await within(dialog).findByText("Ma przy sobie: Klocek drewniany 2 szt."),
  ).toBeInTheDocument();

  fireEvent.change(within(dialog).getByLabelText("Pozycja"), {
    target: { value: BLOCK },
  });
  fireEvent.change(within(dialog).getByLabelText("Ilość"), {
    target: { value: "5" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));

  await waitFor(() => expect(api.issueInventory).toHaveBeenCalledTimes(1));
  expect(api.issueInventory).toHaveBeenCalledWith({
    item_id: BLOCK,
    holder_id: TRIMMER,
    quantity: "5",
  });
  expect(await screen.findByText("Wydano.")).toBeInTheDocument();
});

test("dokument zapisany i zatwierdzony od razu dostaje numer", async () => {
  api.listInventoryBalances.mockResolvedValue([]);
  api.createStockDocument.mockResolvedValue({ id: "doc-1" });
  api.postStockDocument.mockResolvedValue({
    id: "doc-1",
    number: "PZ/2026/0001",
  });

  renderPanel();
  fireEvent.click(await screen.findByRole("tab", { name: "Dokumenty" }));
  fireEvent.click(await screen.findByRole("button", { name: "Nowy dokument" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Pozycja"), {
    target: { value: BLOCK },
  });
  fireEvent.change(within(dialog).getByLabelText("Ilość"), {
    target: { value: "10" },
  });
  fireEvent.change(
    within(dialog).getByLabelText("Cena netto za jednostkę (zł)"),
    { target: { value: "2.5" } },
  );
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz i zatwierdź" }),
  );

  await waitFor(() =>
    expect(api.postStockDocument).toHaveBeenCalledWith("doc-1"),
  );
  expect(api.createStockDocument).toHaveBeenCalledWith(
    expect.objectContaining({
      kind: "PZ",
      target_location_id: WAREHOUSE,
      source_location_id: null,
      lines: [{ item_id: BLOCK, quantity: "10", unit_price_minor: 250 }],
    }),
  );
  expect(
    await screen.findByText("Zatwierdzono dokument PZ/2026/0001."),
  ).toBeInTheDocument();
});

test("bez prawa do prowadzenia magazynu widać tylko swój zapas", async () => {
  api.listInventoryBalances.mockResolvedValue([]);

  renderPanel({ canManage: false });

  expect(
    await screen.findByRole("tab", { name: "Mój zapas" }),
  ).toBeInTheDocument();
  expect(api.listInventoryBalances).toHaveBeenCalledWith({ mine: true });
  expect(screen.queryByRole("button", { name: "Wydaj osobie" })).toBeNull();
  expect(screen.queryByRole("tab", { name: "Dokumenty" })).toBeNull();
  // Lista ludzi to nie jest widok magazynu: pracownik jej nie pobiera.
  expect(api.listMemberships).not.toHaveBeenCalled();
});
