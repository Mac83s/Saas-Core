import axe from "axe-core";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type BookingPrice,
  type BookingPriceChange,
} from "@saas-core/api-client";
import polishMessages from "../../../../../messages/pl.json";
import { PriceHistoryDialog } from "./price-history";
import type { PriceSetup } from "./price-book";

const { api } = vi.hoisted(() => ({
  api: {
    listBookingPriceChanges: vi.fn(),
    readBookingPricesOnDay: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const STAY = "0199a000-0000-7000-8000-0000000000a1";
const setup = {
  services: [
    {
      id: STAY,
      name: "Nocleg w domku",
      time_model: "range",
      range_unit: "night",
      group_ids: [],
      resource_ids: [],
    },
  ],
  groups: [],
  resources: [],
} as unknown as PriceSetup;

function price(overrides: Partial<BookingPrice> = {}): BookingPrice {
  return {
    id: "0199a000-0000-7000-8000-0000000000b1",
    name: "",
    service_id: STAY,
    group_id: null,
    resource_id: null,
    starts_on: null,
    ends_on: null,
    weekdays: [],
    local_from: null,
    local_to: null,
    basis: "per_time_unit",
    amount_minor: 45000,
    currency: "PLN",
    vat_code: "8",
    included_people: null,
    extra_person_amount_minor: null,
    extra_person_per_time_unit: false,
    category_prices: [],
    length_discounts: [],
    active: true,
    version: 2,
    ...overrides,
  };
}

function line(overrides: Partial<BookingPriceChange> = {}): BookingPriceChange {
  return {
    id: "0199a000-0000-7000-8000-0000000000d1",
    price_id: "0199a000-0000-7000-8000-0000000000b1",
    change: "updated",
    recorded_at: "2026-10-04T08:30:00Z",
    actor: { name: "Ola Nowak", email: "ola@example.test" },
    acting_via: "",
    amount_minor: 45000,
    previous_amount_minor: 40000,
    currency: "PLN",
    price: price(),
    ...overrides,
  };
}

function open() {
  return render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <PriceHistoryDialog onOpenChange={() => undefined} setup={setup} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listBookingPriceChanges.mockResolvedValue({
    total: 3,
    page: 1,
    page_size: 10,
    recorded_since: "2026-10-01T09:00:00Z",
    items: [
      line(),
      line({
        id: "0199a000-0000-7000-8000-0000000000d2",
        change: "deleted",
        amount_minor: 60000,
        previous_amount_minor: 60000,
        acting_via: "assistant",
        price: price({ name: "Lipiec", amount_minor: 60000 }),
      }),
      line({
        id: "0199a000-0000-7000-8000-0000000000d3",
        change: "baseline",
        actor: null,
        amount_minor: 40000,
        previous_amount_minor: null,
        price: price({ amount_minor: 40000 }),
      }),
    ],
  });
});

test("the record says who changed which price, when, and the amount before and after", async () => {
  open();
  const dialog = await screen.findByRole("dialog", { name: "Historia cen" });
  const table = await within(dialog).findByRole("table", {
    name: "Zmiany cen",
  });
  expect(api.listBookingPriceChanges).toHaveBeenCalledWith({
    page: 1,
    pageSize: 10,
  });
  expect(
    within(dialog).getByText(/Każda zmiana cennika od 1 paź 2026/),
  ).toBeTruthy();
  expect(within(table).getByText(/400,00\szł → 450,00\szł/)).toBeTruthy();
  expect(within(table).getByText("Ola Nowak")).toBeTruthy();
  // A price deleted since still says what it was, and who asked the assistant.
  expect(
    within(table).getByText(/Usunięta \(ostatnio 600,00\szł\)/),
  ).toBeTruthy();
  expect(within(table).getByText("Ola Nowak (przez asystenta)")).toBeTruthy();
  expect(within(table).getByText("Lipiec")).toBeTruthy();
  // The line the record began with has nobody behind it.
  expect(
    within(table).getByText(/Stan na początek zapisu: 400,00\szł/),
  ).toBeTruthy();
  expect(within(table).getByText("Zapis systemu")).toBeTruthy();
  expect(await axe.run(dialog)).toMatchObject({ violations: [] });
});

test("a chosen day shows the price list as it stood, and a day before the record says so", async () => {
  api.readBookingPricesOnDay.mockResolvedValue({
    day: "2026-10-02",
    as_of: "2026-10-02T22:00:00Z",
    recorded_since: "2026-10-01T09:00:00Z",
    items: [price({ amount_minor: 40000 })],
  });
  open();
  const dialog = await screen.findByRole("dialog", { name: "Historia cen" });
  const show = within(dialog).getByRole("button", { name: "Pokaż cennik" });
  expect((show as HTMLButtonElement).disabled).toBe(true);

  fireEvent.change(within(dialog).getByLabelText("Dzień"), {
    target: { value: "2026-10-02" },
  });
  fireEvent.click(show);
  expect(
    await within(dialog).findByText(/Cena podstawowa .* — 400,00\szł za noc/),
  ).toBeTruthy();
  expect(api.readBookingPricesOnDay).toHaveBeenCalledWith("2026-10-02");

  api.readBookingPricesOnDay.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Bad Request",
      status: 400,
      detail: "",
      code: "invalid",
      correlation_id: null,
      errors: [
        {
          field: "day",
          code: "before_price_history",
          message:
            "Historia cen zaczyna się 2026-10-01: wcześniejszych cen zapis nie zna.",
        },
      ],
    }),
  );
  fireEvent.change(within(dialog).getByLabelText("Dzień"), {
    target: { value: "2026-09-01" },
  });
  fireEvent.click(show);
  expect((await within(dialog).findByRole("alert")).textContent).toBe(
    "Historia cen zaczyna się 2026-10-01: wcześniejszych cen zapis nie zna.",
  );
});
