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
    listInventoryBalances: vi.fn(),
    listMemberships: vi.fn(),
    createInventoryItem: vi.fn(),
    receiveInventory: vi.fn(),
    issueInventory: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const BLOCK = "0192f000-0000-7000-8000-0000000000b1";
const TRIMMER = "0192f000-0000-7000-8000-0000000000c1";

const item = {
  id: BLOCK,
  name: "Klocek drewniany",
  category: "block",
  unit: "piece",
  minimum_quantity: "5.00",
  average_cost_minor: 1250,
  currency: "PLN",
  active: true,
  notes: "",
};

/** Ile czego leży w jednym miejscu; `holder_id` puste to magazyn firmy. */
function balance(quantity: string, holder: string | null) {
  return {
    item_id: BLOCK,
    item_name: item.name,
    category: "block",
    unit: "piece",
    holder_id: holder,
    quantity,
    minimum_quantity: "5.00",
    updated_at: "2026-09-21T08:00:00Z",
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  api.listInventoryItems.mockResolvedValue([item]);
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

function renderPanel() {
  return render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <InventoryPanel canManage canRead />
    </NextIntlClientProvider>,
  );
}

test("wydanie korektorowi pokazuje, co ma przy sobie, i schodzi z magazynu", async () => {
  // Magazyn firmy, zapas pytającego, zapas wskazanej osoby — trzy różne pytania.
  api.listInventoryBalances.mockImplementation(
    (query?: { mine?: boolean; holderId?: string }) => {
      if (query?.mine) return Promise.resolve([]);
      if (query?.holderId) return Promise.resolve([balance("2.00", TRIMMER)]);
      return Promise.resolve([balance("20.00", null)]);
    },
  );

  renderPanel();
  expect(await screen.findByText("Klocek drewniany")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Wydaj korektorowi" }));
  const dialog = await screen.findByRole("dialog");

  fireEvent.change(within(dialog).getByLabelText("Komu"), {
    target: { value: TRIMMER },
  });
  // Dopiero po wskazaniu osoby widać, z czym ona już jeździ.
  expect(
    await within(dialog).findByText("Ma przy sobie: Klocek drewniany 2.00."),
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

test("bez prawa do prowadzenia magazynu nie ma czym wydawać", async () => {
  api.listInventoryBalances.mockResolvedValue([]);

  render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <InventoryPanel canRead />
    </NextIntlClientProvider>,
  );

  expect(await screen.findByText("Mój zapas")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Wydaj korektorowi" })).toBeNull();
  // Lista ludzi to nie jest widok magazynu: korektor jej nie pobiera.
  expect(api.listMemberships).not.toHaveBeenCalled();
});
