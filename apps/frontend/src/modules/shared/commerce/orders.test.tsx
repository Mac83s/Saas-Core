import axe from "axe-core";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type CommerceOptions,
  type Order,
  type OrderPayment,
  type OrderSummary,
} from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { OrderPanel } from "./order-panel";
import { OrdersPanel } from "./orders-panel";

const { api } = vi.hoisted(() => ({
  api: {
    listOrders: vi.fn(),
    readCommerceOptions: vi.fn(),
    readOrder: vi.fn(),
    recordOrderPayment: vi.fn(),
    recordOrderRefund: vi.fn(),
    voidOrderPayment: vi.fn(),
    voidOrderRefund: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const options: CommerceOptions = {
  currency: "PLN",
  statuses: [
    "draft",
    "awaiting_payment",
    "partially_paid",
    "paid",
    "fulfilled",
    "completed",
    "canceled",
    "refunded",
  ],
  channels: ["company_site", "catalog", "office"],
  sources: [{ kind: "booking", prefix: "R" }],
  line_kinds: ["booking", "extra", "discount"],
  tax_rates: ["23", "8", "5", "0", "zw", "np"],
  manual_methods: ["cash", "transfer"],
  max_page_size: 100,
};

const payment: OrderPayment = {
  id: "0199a000-0000-7000-8000-0000000000f1",
  kind: "deposit",
  method: "transfer",
  status: "succeeded",
  amount_minor: 5000,
  paid_at: "2026-10-04T09:00:00Z",
  recorded_by: "Ola Właścicielka",
};

function summary(overrides: Partial<OrderSummary> = {}): OrderSummary {
  return {
    id: "0199a000-0000-7000-8000-000000000001",
    number: "R/2026/0001",
    status: "awaiting_payment",
    channel: "company_site",
    source: "booking",
    placed_at: "2026-10-04T08:30:00Z",
    buyer_name: "Anna Kowalska",
    currency: "PLN",
    gross_minor: 20000,
    ...overrides,
  };
}

function order(overrides: Partial<Order> = {}): Order {
  return {
    ...summary(),
    customer_id: "0199a000-0000-7000-8000-0000000000c1",
    buyer_email: "anna@example.test",
    buyer_phone: "+48 600 100 200",
    amounts: "gross",
    net_minor: 16260,
    vat_minor: 3740,
    revision: 1,
    version: 1,
    paid_minor: 0,
    due_minor: 20000,
    payments: [],
    lines: [
      {
        position: 1,
        kind: "booking",
        name: "Strzyżenie",
        customer_name: "Strzyżenie",
        quantity: 1,
        unit_amount_minor: 15000,
        net_minor: 12195,
        vat_minor: 2805,
        gross_minor: 15000,
        tax_rate: "23",
        source: "booking.appointment",
        source_reference: "0199a000-0000-7000-8000-0000000000a1",
        target: {
          label: "Strzyżenie",
          href: "/panel/calendar?view=day&date=2026-10-12",
          at: "2026-10-12T08:00:00Z",
        },
      },
      {
        position: 2,
        kind: "extra",
        name: "Dojazd",
        customer_name: "Dojazd",
        quantity: 1,
        unit_amount_minor: 5000,
        net_minor: 5000,
        vat_minor: 0,
        gross_minor: 5000,
        tax_rate: "zw",
        source: "booking.appointment",
        source_reference: "0199a000-0000-7000-8000-0000000000a1",
        target: null,
      },
    ],
    revisions: [{ revision: 1, gross_minor: 20000 }],
    consents: [
      {
        kind: "document",
        document_kind: "booking_terms",
        version: 2,
        locale: "pl",
        granted: true,
        created_at: "2026-10-04T08:30:00Z",
      },
      {
        kind: "marketing",
        document_kind: null,
        version: null,
        locale: "pl",
        granted: false,
        created_at: "2026-10-04T08:30:01Z",
      },
    ],
    ...overrides,
  };
}

function wrap(node: React.ReactNode, locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      {node}
    </NextIntlClientProvider>,
  );
}

function refusal(status: number, code: string) {
  return new ApiProblemError({
    type: "about:blank",
    title: code,
    status,
    code,
    detail: code,
    correlation_id: null,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  api.readCommerceOptions.mockResolvedValue(options);
  api.listOrders.mockResolvedValue({
    total: 2,
    page: 1,
    page_size: 25,
    items: [
      summary({
        id: "0199a000-0000-7000-8000-000000000002",
        number: "R/2026/0002",
        status: "canceled",
        channel: "office",
        buyer_name: "Jan Kot",
        gross_minor: 15000,
      }),
      summary(),
    ],
  });
  api.readOrder.mockResolvedValue(order());
});

test("the list shows each order's number, buyer, amount and where it came from", async () => {
  const { container } = wrap(<OrdersPanel />);

  const table = await screen.findByRole("table", { name: "Zamówienia firmy" });
  const rows = within(table).getAllByRole("row").slice(1);
  // A cell carries its column's name, for the phone's cards.
  expect(
    rows.map((row) =>
      within(row)
        .getAllByRole("cell")
        .slice(0, 6)
        .map((cell) => cell.textContent?.replaceAll(/\s/g, " ")),
    ),
  ).toEqual([
    [
      "R/2026/0002",
      "Złożone4 paź 2026, 10:30",
      "KupującyJan Kot",
      "Kwota150,00 zł",
      "StatusAnulowane",
      "SkądBiuro",
    ],
    [
      "R/2026/0001",
      "Złożone4 paź 2026, 10:30",
      "KupującyAnna Kowalska",
      "Kwota200,00 zł",
      "StatusDo zapłaty",
      "SkądStrona firmy",
    ],
  ]);
  expect(
    within(rows[1]!)
      .getByRole("link", { name: "R/2026/0001" })
      .getAttribute("href"),
  ).toBe("/panel/orders/0199a000-0000-7000-8000-000000000001");
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("the server filters and searches, and a narrowed empty list offers the way out", async () => {
  wrap(<OrdersPanel />);
  await screen.findByRole("table", { name: "Zamówienia firmy" });
  expect(api.listOrders).toHaveBeenLastCalledWith({
    page: 1,
    pageSize: 25,
    status: "",
    channel: "",
    q: "",
  });

  api.listOrders.mockResolvedValue({
    total: 0,
    page: 1,
    page_size: 25,
    items: [],
  });
  // The filters' choices are the API's, in the panel's words.
  const status = screen.getByLabelText("Status");
  expect(
    within(status)
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual([
    "Wszystkie",
    "Szkic",
    "Do zapłaty",
    "Opłacone częściowo",
    "Opłacone",
    "Zrealizowane",
    "Zakończone",
    "Anulowane",
    "Zwrócone",
  ]);
  fireEvent.change(status, { target: { value: "paid" } });
  fireEvent.change(screen.getByLabelText("Szukaj zamówienia"), {
    target: { value: " kowalska " },
  });

  await waitFor(() =>
    expect(api.listOrders).toHaveBeenLastCalledWith({
      page: 1,
      pageSize: 25,
      status: "paid",
      channel: "",
      q: "kowalska",
    }),
  );
  expect(
    await screen.findByText(
      "Żadne zamówienie nie pasuje do wyszukiwania i filtrów.",
    ),
  ).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Wyczyść wyszukiwanie i filtry" }),
  );
  await waitFor(() =>
    expect(api.listOrders).toHaveBeenLastCalledWith({
      page: 1,
      pageSize: 25,
      status: "",
      channel: "",
      q: "",
    }),
  );
});

test("a plan without orders is said calmly, with the way to the plans for the owner only", async () => {
  api.listOrders.mockRejectedValue(refusal(403, "entitlement_required"));

  const owner = wrap(<OrdersPanel canManageBilling />);
  expect(
    await screen.findByText("Plan firmy nie ma jeszcze zamówień"),
  ).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Zobacz plany" }).getAttribute("href"),
  ).toBe("/panel/settings/billing");
  owner.unmount();

  wrap(<OrdersPanel />);
  expect(await screen.findByText(/poproś właściciela firmy/)).toBeTruthy();
  expect(screen.queryByRole("link", { name: "Zobacz plany" })).toBeNull();
});

test("a failed load can be tried again and a refusal says who reads orders", async () => {
  api.listOrders.mockRejectedValueOnce(new Error("offline"));
  const first = wrap(<OrdersPanel />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Spróbuj ponownie" }),
  );
  expect(
    await screen.findByRole("table", { name: "Zamówienia firmy" }),
  ).toBeTruthy();
  first.unmount();

  api.listOrders.mockRejectedValue(
    refusal(403, "organization_permission_denied"),
  );
  wrap(<OrdersPanel />);
  expect(
    await screen.findByText(
      "Zamówienia czyta właściciel, administrator i kierownik firmy.",
    ),
  ).toBeTruthy();
});

test("an order shows the buyer, its lines as the server priced them and the way to the visit", async () => {
  const { container } = wrap(
    <OrderPanel orderId="0199a000-0000-7000-8000-000000000001" />,
  );

  expect(
    await screen.findByRole("heading", { name: "Zamówienie R/2026/0001" }),
  ).toBeTruthy();
  expect(api.readOrder).toHaveBeenCalledWith(
    "0199a000-0000-7000-8000-000000000001",
  );
  expect(screen.getByText("Do zapłaty")).toBeTruthy();
  expect(screen.getByText("Rezerwacja")).toBeTruthy();
  expect(screen.getByText("Strona firmy")).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "anna@example.test" })
      .getAttribute("href"),
  ).toBe("mailto:anna@example.test");
  expect(
    screen.getByRole("link", { name: "+48 600 100 200" }).getAttribute("href"),
  ).toBe("tel:+48600100200");

  const table = screen.getByRole("table", { name: "Pozycje zamówienia" });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(
    rows.map((row) =>
      within(row)
        .getAllByRole("cell")
        .slice(1)
        .map((cell) => cell.textContent?.replaceAll(/\s/g, " ")),
    ),
  ).toEqual([
    [
      "Ilość1",
      "Cena brutto150,00 zł",
      "VAT23%",
      "Netto121,95 zł",
      "Podatek28,05 zł",
      "Brutto150,00 zł",
    ],
    [
      "Ilość1",
      "Cena brutto50,00 zł",
      "VATzw.",
      "Netto50,00 zł",
      "Podatek0,00 zł",
      "Brutto50,00 zł",
    ],
  ]);
  // The line of the visit leads to its day in the calendar.
  expect(
    within(rows[0]!)
      .getByRole("link", {
        name: "Strzyżenie, 12 paź 2026, 10:00 — zobacz w kalendarzu",
      })
      .getAttribute("href"),
  ).toBe("/panel/calendar?view=day&date=2026-10-12");
  expect(within(rows[1]!).queryByRole("link")).toBeNull();
  // The totals are the server's.
  expect(
    screen.getByText("Razem netto").nextElementSibling?.textContent,
  ).toMatch(/162,60/);
  expect(
    screen.getByText("Razem brutto").nextElementSibling?.textContent,
  ).toMatch(/200,00/);
  expect(screen.queryByText(/Kwota zmieniła się/)).toBeNull();
  // What the buyer accepted, from the consent journal.
  const consents = screen.getByRole("table", {
    name: "Zgody klienta przy tym zamówieniu",
  });
  expect(
    within(consents)
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("cell")[0]?.textContent),
  ).toEqual([
    "Regulamin rezerwacji, wersja 2 (PL)",
    "Zgoda marketingowa — wycofana",
  ]);
  expect(
    screen.getByRole("link", { name: "Zamówienia" }).getAttribute("href"),
  ).toBe("/panel/orders");
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("an order priced again says what it came to before, in English too", async () => {
  api.readOrder.mockResolvedValue(
    order({
      revision: 2,
      amounts: "net",
      buyer_email: "",
      buyer_phone: "",
      consents: [],
      revisions: [
        { revision: 1, gross_minor: 15000 },
        { revision: 2, gross_minor: 20000 },
      ],
    }),
  );

  wrap(<OrderPanel orderId="0199a000-0000-7000-8000-000000000001" />, "en");

  expect(
    await screen.findByText(
      /The amount changed when the booking got a new price\. Before: PLN\s150\.00\./,
    ),
  ).toBeTruthy();
  expect(screen.getByRole("columnheader", { name: "Net price" })).toBeTruthy();
  expect(screen.getAllByText("not given")).toHaveLength(2);
  expect(
    screen.getByText("The customer accepted no document with this order."),
  ).toBeTruthy();
});

test("an order that is not there says so", async () => {
  api.readOrder.mockRejectedValue(refusal(404, "not_found"));

  wrap(<OrderPanel orderId="0199a000-0000-7000-8000-00000000dead" />);

  expect(await screen.findByText("Nie ma takiego zamówienia.")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Spróbuj ponownie" })).toBeNull();
});

test("what was paid and what is left are the server's, and only who may marks a payment", async () => {
  api.readOrder.mockResolvedValue(
    order({
      status: "partially_paid",
      paid_minor: 5000,
      due_minor: 15000,
      payments: [payment],
    }),
  );

  const reader = wrap(
    <OrderPanel orderId="0199a000-0000-7000-8000-000000000001" />,
  );
  const table = await screen.findByRole("table", {
    name: "Wpłaty do tego zamówienia",
  });
  expect(screen.getByText("Wpłacono").nextElementSibling?.textContent).toMatch(
    /50,00/,
  );
  expect(
    screen.getByText("Zostało do zapłaty").nextElementSibling?.textContent,
  ).toMatch(/150,00/);
  const row = within(table).getAllByRole("row")[1]!;
  expect(
    within(row)
      .getAllByRole("cell")
      .map((cell) => cell.textContent?.replaceAll(/\s/g, " ")),
  ).toEqual([
    "4 paź 2026, 11:00",
    "JakPrzelew",
    "Kwota50,00 zł",
    "StatusWpłacona",
    "Kto oznaczyłOla Właścicielka",
  ]);
  // Without the right there is nothing to press.
  expect(screen.queryByRole("button", { name: "Oznacz wpłatę" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Wycofaj" })).toBeNull();
  reader.unmount();

  wrap(
    <OrderPanel
      canManagePayments
      orderId="0199a000-0000-7000-8000-000000000001"
    />,
  );
  expect(
    await screen.findByRole("button", { name: "Oznacz wpłatę" }),
  ).toBeTruthy();
  expect(await screen.findByRole("button", { name: "Wycofaj" })).toBeTruthy();
});

test("marking a payment starts from what is left, sends the version read and shows the order it got back", async () => {
  const before = order({ version: 3 });
  api.readOrder.mockResolvedValue(before);
  api.recordOrderPayment.mockResolvedValue(
    order({
      status: "paid",
      version: 4,
      paid_minor: 20000,
      due_minor: 0,
      payments: [
        { ...payment, kind: "full", method: "cash", amount_minor: 20000 },
      ],
    }),
  );
  wrap(
    <OrderPanel
      canManagePayments
      orderId="0199a000-0000-7000-8000-000000000001"
    />,
  );

  fireEvent.click(await screen.findByRole("button", { name: "Oznacz wpłatę" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Oznacz wpłatę do zamówienia R/2026/0001",
  });
  expect(within(dialog).getByText(/Zostało do zapłaty: 200,00/)).toBeTruthy();
  const amount = within(dialog).getByLabelText("Kwota (PLN)");
  expect((amount as HTMLInputElement).value).toBe("200,00");
  // The methods are the API's.
  const method = await within(dialog).findByRole("option", {
    name: "Na miejscu (gotówka albo karta)",
  });
  expect(method).toBeTruthy();
  fireEvent.change(amount, { target: { value: "abc" } });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz wpłatę" }),
  );
  expect(
    await within(dialog).findByText("Wpisz kwotę, np. 150 albo 150,50."),
  ).toBeTruthy();
  expect(api.recordOrderPayment).not.toHaveBeenCalled();

  fireEvent.change(amount, { target: { value: "200" } });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz wpłatę" }),
  );
  await waitFor(() =>
    expect(api.recordOrderPayment).toHaveBeenCalledWith(
      "0199a000-0000-7000-8000-000000000001",
      { amount_minor: 20000, method: "cash", expected_version: 3 },
    ),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(await screen.findByText("Opłacone")).toBeTruthy();
  expect(screen.getByText(/Zapisano wpłatę: 200,00/)).toBeTruthy();
  // Nothing is left to pay: nothing more to mark.
  expect(screen.queryByRole("button", { name: "Oznacz wpłatę" })).toBeNull();
});

test("an order that waits for a prepayment says until when, and marking starts from what is awaited", async () => {
  const awaited: OrderPayment = {
    ...payment,
    status: "requires_payment",
    amount_minor: 6000,
    due_at: "2026-10-07T08:30:00Z",
    paid_at: null,
    recorded_by: "",
  };
  api.readOrder.mockResolvedValue(order({ version: 2, payments: [awaited] }));
  api.recordOrderPayment.mockResolvedValue(
    order({
      status: "partially_paid",
      version: 3,
      paid_minor: 6000,
      due_minor: 14000,
      payments: [{ ...payment, amount_minor: 6000 }],
    }),
  );
  wrap(
    <OrderPanel
      canManagePayments
      orderId="0199a000-0000-7000-8000-000000000001"
    />,
  );

  // Until when, and what marking it does.
  const note = await screen.findByRole("note");
  expect(note).toHaveTextContent(/czeka na wpłatę 60,00\szł do 7 paź/);
  expect(note).toHaveTextContent(/rezerwacja zostanie potwierdzona/);
  const table = screen.getByRole("table", {
    name: "Wpłaty do tego zamówienia",
  });
  expect(within(table).getByText("Czeka na wpłatę")).toBeTruthy();
  expect(within(table).getByText(/^do 7 paź/)).toBeTruthy();
  // An awaited payment is not one to take back.
  expect(within(table).queryByRole("button", { name: "Wycofaj" })).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "Oznacz wpłatę" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Oznacz wpłatę do zamówienia R/2026/0001",
  });
  expect(
    within(dialog).getByText(/Rezerwacja czeka na wpłatę 60,00/),
  ).toBeTruthy();
  // The amount awaited, by the transfer it was asked for.
  expect(
    (within(dialog).getByLabelText("Kwota (PLN)") as HTMLInputElement).value,
  ).toBe("60,00");
  await waitFor(() =>
    expect(
      (within(dialog).getByLabelText("Jak zapłacono") as HTMLSelectElement)
        .value,
    ).toBe("transfer"),
  );
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz wpłatę" }),
  );
  await waitFor(() =>
    expect(api.recordOrderPayment).toHaveBeenCalledWith(
      "0199a000-0000-7000-8000-000000000001",
      { amount_minor: 6000, method: "transfer", expected_version: 2 },
    ),
  );
  await waitFor(() => expect(screen.queryByRole("note")).toBeNull());
});

test("a draft — a request the company has not answered — has no number and takes no payment", async () => {
  api.readOrder.mockResolvedValue(order({ number: "", status: "draft" }));
  wrap(
    <OrderPanel
      canManagePayments
      orderId="0199a000-0000-7000-8000-000000000001"
    />,
  );

  expect(
    await screen.findByRole("heading", { name: "Zamówienie bez numeru" }),
  ).toBeTruthy();
  expect(screen.getByText("Szkic")).toBeTruthy();
  expect(await screen.findByRole("note")).toHaveTextContent(
    /czeka, aż firma odpowie na prośbę klienta/,
  );
  expect(screen.queryByRole("button", { name: "Oznacz wpłatę" })).toBeNull();
});

test("the server's refusal is shown in the dialog and a stale order is read again", async () => {
  api.readOrder.mockResolvedValue(order());
  api.recordOrderPayment.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Bad request",
      status: 400,
      code: "invalid",
      detail: "invalid",
      correlation_id: null,
      errors: [
        {
          field: "amount_minor",
          code: "amount_exceeds_due",
          message: "Kwota jest większa niż to, co zostało do zapłaty.",
        },
      ],
    }),
  );
  wrap(
    <OrderPanel
      canManagePayments
      orderId="0199a000-0000-7000-8000-000000000001"
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Oznacz wpłatę" }));
  const dialog = await screen.findByRole("dialog");
  await within(dialog).findByRole("option", { name: "Przelew" });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz wpłatę" }),
  );
  expect(
    await within(dialog).findByText(
      "Kwota jest większa niż to, co zostało do zapłaty.",
    ),
  ).toBeTruthy();

  api.recordOrderPayment.mockRejectedValueOnce(
    refusal(409, "order_version_conflict"),
  );
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz wpłatę" }),
  );
  expect(
    await screen.findByText(/Ktoś zmienił to zamówienie w międzyczasie/),
  ).toBeTruthy();
  await waitFor(() => expect(api.readOrder).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("a payment marked by mistake is taken back after a question, and a canceled order says what to give back", async () => {
  const paid = order({
    status: "paid",
    version: 2,
    paid_minor: 20000,
    due_minor: 0,
    payments: [{ ...payment, kind: "full", amount_minor: 20000 }],
  });
  api.readOrder.mockResolvedValue(paid);
  api.voidOrderPayment.mockResolvedValue(
    order({
      version: 3,
      payments: [
        { ...payment, kind: "full", amount_minor: 20000, status: "canceled" },
      ],
    }),
  );
  const first = wrap(
    <OrderPanel
      canManagePayments
      orderId="0199a000-0000-7000-8000-000000000001"
    />,
  );

  fireEvent.click(await screen.findByRole("button", { name: "Wycofaj" }));
  const dialog = await screen.findByRole("dialog", {
    name: /Wycofać wpłatę 200,00/,
  });
  expect(
    within(dialog).getByText(/To nie jest zwrot pieniędzy klientowi/),
  ).toBeTruthy();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Wycofaj wpłatę" }),
  );
  await waitFor(() =>
    expect(api.voidOrderPayment).toHaveBeenCalledWith(
      "0199a000-0000-7000-8000-000000000001",
      payment.id,
      2,
    ),
  );
  expect(await screen.findByText("Wycofana")).toBeTruthy();
  expect(screen.getByText(/Wycofano wpłatę: 200,00/)).toBeTruthy();
  // A payment taken back has nothing more to take back.
  expect(screen.queryByRole("button", { name: "Wycofaj" })).toBeNull();
  first.unmount();

  api.readOrder.mockResolvedValue(
    order({
      ...paid,
      status: "canceled",
      due_minor: 0,
      refund_owed_minor: 20000,
    }),
  );
  wrap(
    <OrderPanel
      canManagePayments
      orderId="0199a000-0000-7000-8000-000000000001"
    />,
  );
  expect(
    (await screen.findByText("Do oddania klientowi")).nextElementSibling
      ?.textContent,
  ).toMatch(/200,00/);
  expect(screen.queryByText("Zostało do zapłaty")).toBeNull();
  expect(screen.queryByText("Zostaje po anulowaniu")).toBeNull();
  expect(screen.queryByRole("button", { name: "Oznacz wpłatę" })).toBeNull();
});

test("a canceled order says what its terms give back, and the company marks the refund (ADR-073 §8)", async () => {
  const canceled = order({
    status: "canceled",
    version: 4,
    paid_minor: 6000,
    due_minor: 14000,
    refunded_minor: 0,
    refund_owed_minor: 3000,
    refunds: [],
    payments: [{ ...payment, amount_minor: 6000 }],
  });
  const refund = {
    id: "0199a000-0000-7000-8000-0000000000e1",
    method: "transfer" as const,
    status: "succeeded" as const,
    amount_minor: 3000,
    reason: "",
    refunded_at: "2026-10-04T10:00:00Z",
    recorded_by: "Ola Właścicielka",
  };
  const refunded = order({
    ...canceled,
    version: 5,
    paid_minor: 3000,
    refunded_minor: 3000,
    refund_owed_minor: 0,
    refunds: [refund],
  });
  api.readOrder.mockResolvedValue(canceled);
  api.recordOrderRefund.mockResolvedValue(refunded);
  api.voidOrderRefund.mockResolvedValue(
    order({
      ...canceled,
      version: 6,
      refunds: [{ ...refund, status: "canceled" }],
    }),
  );
  const { container } = wrap(
    <OrderPanel
      canManagePayments
      orderId="0199a000-0000-7000-8000-000000000001"
    />,
  );

  // Half of the prepayment goes back; the other half stays with the company.
  const owed = await screen.findByText("Do oddania klientowi");
  expect(owed.nextElementSibling?.textContent).toMatch(/30,00/);
  expect(
    screen.getByText("Zostaje po anulowaniu").nextElementSibling?.textContent,
  ).toMatch(/30,00/);
  const refunds = screen.getByRole("region", { name: "Zwroty" });
  expect(
    within(refunds).getByText(/Do oddania klientowi: 30,00\szł\. Kwota wynika/),
  ).toBeTruthy();
  expect(
    within(refunds).getByText("Nikt jeszcze nie oznaczył zwrotu."),
  ).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Oznacz zwrot" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Oznacz zwrot do zamówienia R/2026/0001",
  });
  const amount = within(dialog).getByLabelText("Kwota (PLN)");
  // The amount starts at what the terms owe; within it no reason is asked for.
  await waitFor(() => expect(amount).toHaveValue("30,00"));
  expect(
    within(dialog).getByLabelText("Powód zwrotu (opcjonalnie)"),
  ).toBeTruthy();
  // Beyond the terms the company says why — before anything is sent.
  fireEvent.change(amount, { target: { value: "50" } });
  await waitFor(() =>
    expect(
      within(dialog).getByRole("button", { name: "Zapisz zwrot" }),
    ).toBeEnabled(),
  );
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz zwrot" }));
  expect(
    await within(dialog).findByText(
      "Podaj powód zwrotu ponad to, co wynika z warunków zamówienia.",
    ),
  ).toBeTruthy();
  expect(api.recordOrderRefund).not.toHaveBeenCalled();
  expect((await axe.run(dialog)).violations).toEqual([]);
  fireEvent.change(amount, { target: { value: "30" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz zwrot" }));
  await waitFor(() =>
    expect(api.recordOrderRefund).toHaveBeenCalledWith(
      "0199a000-0000-7000-8000-000000000001",
      {
        amount_minor: 3000,
        method: "transfer",
        reason: "",
        expected_version: 4,
      },
    ),
  );
  expect(await screen.findByText(/Zapisano zwrot: 30,00/)).toBeTruthy();
  expect(
    screen.getByText("Zwrócono klientowi").nextElementSibling?.textContent,
  ).toMatch(/30,00/);
  // What came in is still said whole: 30 stayed and 30 went back.
  expect(screen.getByText("Wpłacono").nextElementSibling?.textContent).toMatch(
    /60,00/,
  );
  expect(screen.queryByText("Do oddania klientowi")).toBeNull();
  expect((await axe.run(container)).violations).toEqual([]);

  // A refund marked by mistake is taken back after a question.
  const row = within(screen.getByRole("region", { name: "Zwroty" }));
  fireEvent.click(row.getByRole("button", { name: "Wycofaj" }));
  const question = await screen.findByRole("dialog", {
    name: /Wycofać zwrot 30,00/,
  });
  fireEvent.click(
    within(question).getByRole("button", { name: "Wycofaj zwrot" }),
  );
  await waitFor(() =>
    expect(api.voidOrderRefund).toHaveBeenCalledWith(
      "0199a000-0000-7000-8000-000000000001",
      refund.id,
      5,
    ),
  );
  expect(await screen.findByText(/Wycofano zwrot: 30,00/)).toBeTruthy();
  expect(await screen.findByText("Wycofany")).toBeTruthy();
});

test("the rest due by a transfer is said without a threat, and late it is the company's decision", async () => {
  vi.useFakeTimers({ toFake: ["Date"], shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-10-04T12:00:00Z"));
  const balance: OrderPayment = {
    ...payment,
    id: "0199a000-0000-7000-8000-0000000000f2",
    kind: "balance",
    status: "requires_payment",
    amount_minor: 14000,
    due_at: "2026-10-20T08:00:00Z",
    paid_at: null,
    recorded_by: "",
  };
  const partly = order({
    status: "partially_paid",
    version: 3,
    paid_minor: 6000,
    due_minor: 14000,
    payments: [{ ...payment, amount_minor: 6000 }, balance],
  });
  api.readOrder.mockResolvedValue(partly);
  const first = wrap(
    <OrderPanel
      canManagePayments
      orderId="0199a000-0000-7000-8000-000000000001"
    />,
  );
  expect(
    await screen.findByText(/Reszta ceny, 140,00\szł, ma wpłynąć przelewem do/),
  ).toBeTruthy();
  expect(screen.queryByText(/rezerwacja wygaśnie/)).toBeNull();
  // Marking it promises no confirmation: the booking is confirmed already.
  fireEvent.click(screen.getByRole("button", { name: "Oznacz wpłatę" }));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).queryByText(/potwierdzi rezerwację/)).toBeNull();
  await waitFor(() =>
    expect(within(dialog).getByLabelText("Kwota (PLN)")).toHaveValue("140,00"),
  );
  first.unmount();

  api.readOrder.mockResolvedValue(
    order({
      ...partly,
      payments: [
        { ...payment, amount_minor: 6000 },
        { ...balance, due_at: "2026-10-01T08:00:00Z" },
      ],
    }),
  );
  wrap(
    <OrderPanel
      canManagePayments
      orderId="0199a000-0000-7000-8000-000000000001"
    />,
  );
  expect(
    await screen.findByText(
      /Dopłata 140,00\szł miała wpłynąć do .* Rezerwacja pozostaje potwierdzona/,
    ),
  ).toBeTruthy();
  vi.useRealTimers();
});
