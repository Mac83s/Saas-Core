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
import { InventoryPanel, type InventorySection } from "./inventory-panel";

vi.mock("#i18n/navigation", () => ({ Link: "a" }));

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
    receiveInventory: vi.fn(),
    createStockDocument: vi.fn(),
    postStockDocument: vi.fn(),
    listInventoryLots: vi.fn(),
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
  api.receiveInventory.mockResolvedValue({});
  api.listInventoryLots.mockResolvedValue([]);
});

function renderPanel(
  props: { canManage?: boolean; section?: InventorySection } = {
    canManage: true,
  },
) {
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
  // The page's action is in its header; the row repeats it for its item.
  const [pageAction] = screen.getAllByRole("button", { name: "Wydaj osobie" });
  expect(pageAction.closest("header")).not.toBeNull();

  fireEvent.click(pageAction);
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
    id: expect.any(String),
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

  renderPanel({ canManage: true, section: "documents" });
  // What PZ or MM means sits next to the list, not in a manual.
  expect(
    await screen.findByRole("complementary", { name: "Pomoc" }),
  ).toHaveTextContent("Rodzaje dokumentów");
  expect(
    screen.getByRole("heading", { level: 1, name: "Dokumenty" }),
  ).toBeInTheDocument();
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

  const { unmount } = renderPanel({ canManage: false });

  await waitFor(() =>
    expect(api.listInventoryBalances).toHaveBeenCalledWith({ mine: true }),
  );
  expect(
    screen.getByRole("heading", { level: 1, name: "Mój zapas" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Wydaj osobie" })).toBeNull();
  // Lista ludzi to nie jest widok magazynu: pracownik jej nie pobiera.
  expect(api.listMemberships).not.toHaveBeenCalled();
  unmount();

  // Dokumenty pod własnym adresem: bez prawa — informacja, nie zapytania.
  api.listInventoryItems.mockClear();
  renderPanel({ canManage: false, section: "documents" });
  expect(
    await screen.findByText("Brak dostępu do magazynu"),
  ).toBeInTheDocument();
  expect(api.listInventoryItems).not.toHaveBeenCalled();
});

test("przyjęcie z wiersza stanu ma już wybraną pozycję", async () => {
  api.listInventoryBalances.mockResolvedValue([
    balance("20.000", WAREHOUSE, null),
  ]);
  renderPanel();
  const row = (await screen.findByText("Klocek drewniany")).closest("tr")!;
  fireEvent.click(
    within(row).getByRole("button", { name: "Przyjmij dostawę" }),
  );
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByLabelText("Pozycja")).toHaveValue(BLOCK);
});

const DRUG = "0192f000-0000-7000-8000-0000000000b2";
const LOT_OLD = "0192f000-0000-7000-8000-0000000000e1";
const LOT_NEW = "0192f000-0000-7000-8000-0000000000e2";
const drug = {
  ...item,
  id: DRUG,
  name: "Oksytetracyklina",
  unit: "ml",
  system_key: "",
  tracks_lots: true,
};

function lot(id: string, number: string, expires: string, status: string) {
  return {
    lot_id: id,
    item_id: DRUG,
    item_name: drug.name,
    unit: "ml",
    number,
    expires_on: expires,
    status,
    location_id: WAREHOUSE,
    location_name: "Magazyn główny",
    holder_id: null,
    quantity: "50.000",
  };
}

test("lek z partiami: stan mówi o najbliższej ważności, a przyjęcie pyta o partię", async () => {
  api.listInventoryItems.mockResolvedValue([item, drug]);
  api.listInventoryBalances.mockResolvedValue([
    {
      ...balance("50.000", WAREHOUSE, null),
      item_id: DRUG,
      item_name: drug.name,
      unit: "ml",
      tracks_lots: true,
      nearest_expiry: "2026-10-01",
      lot_status: "expiring",
    },
  ]);
  renderPanel();
  const row = (await screen.findByText("Oksytetracyklina")).closest("tr")!;
  expect(row).toHaveTextContent("1 paź 2026");
  expect(within(row).getByText("Kończy się ważność")).toBeInTheDocument();

  const [receive] = screen.getAllByRole("button", { name: "Przyjmij dostawę" });
  fireEvent.click(receive);
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).queryByLabelText("Partia")).toBeNull();
  fireEvent.change(within(dialog).getByLabelText("Pozycja"), {
    target: { value: DRUG },
  });
  fireEvent.change(within(dialog).getByLabelText("Partia"), {
    target: { value: "L-2026-09" },
  });
  fireEvent.change(within(dialog).getByLabelText("Ważna do"), {
    target: { value: "2027-03-31" },
  });
  fireEvent.change(within(dialog).getByLabelText("Ilość"), {
    target: { value: "100" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(api.receiveInventory).toHaveBeenCalledWith(
      expect.objectContaining({
        item_id: DRUG,
        lot_number: "L-2026-09",
        expires_on: "2027-03-31",
      }),
    ),
  );
});

test("strona partii: od najkrótszej ważności, po terminie na czerwono", async () => {
  api.listInventoryItems.mockResolvedValue([item, drug]);
  api.listInventoryLots.mockResolvedValue([
    lot(LOT_OLD, "L-OLD", "2026-09-01", "expired"),
    lot(LOT_NEW, "L-NEW", "2027-06-30", "ok"),
  ]);
  renderPanel({ canManage: true, section: "lots" });
  expect(await screen.findByText("Partia: L-OLD")).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { level: 1, name: "Partie i ważność" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Po terminie", { selector: "span" }),
  ).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Ważność"), {
    target: { value: "expired" },
  });
  expect(screen.queryByText("Partia: L-NEW")).toBeNull();
  expect(screen.getByText("Partia: L-OLD")).toBeInTheDocument();
});

test("rozchód leku może wskazać partię; bez niej idzie najkrótsza ważność", async () => {
  api.listInventoryItems.mockResolvedValue([item, drug]);
  api.listInventoryBalances.mockResolvedValue([]);
  api.listInventoryLots.mockResolvedValue([
    lot(LOT_NEW, "L-NEW", "2027-06-30", "ok"),
  ]);
  api.createStockDocument.mockResolvedValue({ id: "doc-2" });
  api.postStockDocument.mockResolvedValue({
    id: "doc-2",
    number: "RW/2026/0001",
  });

  renderPanel({ canManage: true, section: "documents" });
  fireEvent.click(await screen.findByRole("button", { name: "Nowy dokument" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Rodzaj"), {
    target: { value: "RW" },
  });
  fireEvent.change(within(dialog).getByLabelText("Pozycja"), {
    target: { value: DRUG },
  });
  const lotField = within(dialog).getByLabelText("Partia");
  expect(lotField).toHaveValue("");
  expect(
    await within(dialog).findByRole("option", { name: /L-NEW/ }),
  ).toBeInTheDocument();
  fireEvent.change(lotField, { target: { value: LOT_NEW } });
  fireEvent.change(within(dialog).getByLabelText("Ilość"), {
    target: { value: "2" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz i zatwierdź" }),
  );
  await waitFor(() =>
    expect(api.createStockDocument).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "RW",
        lines: [
          {
            item_id: DRUG,
            quantity: "2",
            unit_price_minor: null,
            lot_id: LOT_NEW,
          },
        ],
      }),
    ),
  );
});
