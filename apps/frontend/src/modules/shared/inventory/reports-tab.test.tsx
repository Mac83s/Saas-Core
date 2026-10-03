import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import axe from "axe-core";
import { beforeEach, expect, test, vi } from "vitest";

import englishMessages from "../../../../messages/en.json";
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
    getInventoryStockValue: vi.fn(),
    getInventoryUsage: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const usageRow = {
  key: "v1",
  name: "Strzyżenie",
  quantity: null,
  unit: "",
  cost_minor: 2200,
  sold_minor: 8000,
  currency: "PLN",
  documents: 2,
  at: "2026-10-02T09:00:00Z",
  service_name: "Strzyżenie",
  customer_name: "Jan Kowalski",
  person_name: "Paweł Pracownik",
};

beforeEach(() => {
  vi.resetAllMocks();
  api.listInventoryItems.mockResolvedValue([]);
  api.listInventoryCategories.mockResolvedValue([]);
  api.listSuppliers.mockResolvedValue([]);
  api.listMemberships.mockResolvedValue([]);
  api.listStockLocations.mockResolvedValue([]);
  api.getInventoryStockValue.mockResolvedValue({
    group: "item",
    rows: [
      {
        key: "i1",
        name: "Rękawiczki",
        kind: "",
        quantity: "4.000",
        unit: "pack",
        average_cost_minor: 1000,
        value_minor: 4000,
        currency: "PLN",
      },
    ],
    totals: [{ currency: "PLN", value_minor: 4000 }],
  });
  api.getInventoryUsage.mockResolvedValue({
    group: "visit",
    from: "2026-10-01",
    to: "2026-10-03",
    total: 2,
    page: 1,
    page_size: 50,
    rows: [
      usageRow,
      {
        ...usageRow,
        key: "",
        name: "",
        cost_minor: 400,
        sold_minor: 0,
        at: null,
        customer_name: "",
        person_name: "",
      },
    ],
    totals: [{ currency: "PLN", cost_minor: 2600, sold_minor: 8000 }],
  });
});

function renderReports(locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <InventoryPanel
        canManage
        canRead
        section="reports"
        zone="Europe/Warsaw"
      />
    </NextIntlClientProvider>,
  );
}

test("wartość stanu: pozycja, ilość, średnia cena i razem", async () => {
  renderReports();
  expect(await screen.findByText("Rękawiczki")).toBeInTheDocument();
  expect(screen.getByText("4 opak.")).toBeInTheDocument();
  expect(screen.getByText(/Razem na stanie: 40,00\szł/)).toBeInTheDocument();
  expect(api.getInventoryStockValue).toHaveBeenCalledWith({
    group: "item",
    locationId: undefined,
  });
});

test("koszt wizyty: okres firmy idzie do API, a wiersz bez wizyty ma swoją nazwę", async () => {
  renderReports();
  await screen.findByText("Rękawiczki");
  fireEvent.change(screen.getByLabelText("Raport"), {
    target: { value: "usage:visit" },
  });
  expect(await screen.findByText("Jan Kowalski")).toBeInTheDocument();
  expect(
    screen.getByText("Poza wizytami (korekty, straty)"),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Razem koszt: 26,00\szł, sprzedaż netto: 80,00\szł/),
  ).toBeInTheDocument();
  await waitFor(() =>
    expect(api.getInventoryUsage).toHaveBeenCalledWith(
      expect.objectContaining({
        group: "visit",
        page: 1,
        from: expect.stringMatching(/^\d{4}-\d{2}-01$/),
        to: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      }),
    ),
  );
  expect(screen.getByLabelText("Okres")).toBeInTheDocument();
});

test.each(["pl", "en"] as const)(
  "raporty bez naruszeń axe (%s)",
  async (locale) => {
    renderReports(locale);
    await screen.findByText("Rękawiczki");
    // The page's landmark is the layout's, not this panel's.
    const results = await axe.run(document.body, {
      rules: { region: { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  },
);
