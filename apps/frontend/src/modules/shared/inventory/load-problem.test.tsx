import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError } from "@saas-core/api-client";

import polishMessages from "../../../../messages/pl.json";
import { InventoryPanel } from "./inventory-panel";

vi.mock("#i18n/navigation", () => ({ Link: "a" }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

const { api } = vi.hoisted(() => ({
  api: {
    listInventoryItems: vi.fn(),
    listInventoryCategories: vi.fn(),
    listStockLocations: vi.fn(),
    listSuppliers: vi.fn(),
    listMemberships: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const refused = (code: string) =>
  new ApiProblemError({
    type: "about:blank",
    title: "Odmowa",
    status: 403,
    code,
    detail: "",
  } as ConstructorParameters<typeof ApiProblemError>[0]);

beforeEach(() => {
  vi.resetAllMocks();
  for (const call of Object.values(api)) call.mockResolvedValue([]);
});

function renderPanel(canManageBilling: boolean) {
  return render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <InventoryPanel canManageBilling={canManageBilling} canRead />
    </NextIntlClientProvider>,
  );
}

test("plan bez magazynu to propozycja, z drogą do planów tylko dla tego, kto je zmienia", async () => {
  api.listInventoryItems.mockRejectedValue(refused("entitlement_required"));
  const owner = renderPanel(true);
  expect(
    await screen.findByText("Magazyn nie jest częścią Twojego planu"),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Porównaj plany" })).toHaveAttribute(
    "href",
    "/panel/settings/billing?feature=inventory.enabled",
  );
  expect(screen.queryByText(/Odśwież stronę/)).not.toBeInTheDocument();
  owner.unmount();

  renderPanel(false);
  expect(
    await screen.findByText(/Plan zmienia właściciel konta/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Porównaj plany" }),
  ).not.toBeInTheDocument();
});

test("brak uprawnienia mówi o dostępie, nie każe odświeżać", async () => {
  api.listInventoryItems.mockRejectedValue(
    refused("organization_permission_denied"),
  );
  renderPanel(false);
  expect(
    await screen.findByText(/Nie masz dostępu do magazynu/),
  ).toBeInTheDocument();
  expect(screen.queryByText(/Odśwież stronę/)).not.toBeInTheDocument();
});

test("„Odśwież stronę” tylko wtedy, gdy zawiodło samo połączenie", async () => {
  api.listInventoryItems.mockRejectedValue(new TypeError("Failed to fetch"));
  renderPanel(true);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Nie udało się wczytać magazynu. Odśwież stronę.",
  );
});
