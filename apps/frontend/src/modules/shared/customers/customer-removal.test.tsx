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

import type { CustomerFound } from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { CustomerRemovalPanel } from "./customer-removal-panel";

const { api } = vi.hoisted(() => ({
  api: {
    searchCustomers: vi.fn(),
    previewCustomerAnonymization: vi.fn(),
    anonymizeCustomer: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const ANNA = "0199a000-0000-7000-8000-0000000000c1";

function customer(overrides: Partial<CustomerFound> = {}): CustomerFound {
  return {
    customer_id: ANNA,
    name: "Anna Kowalska",
    email: "anna@example.test",
    phone: "+48 600 100 200",
    links: [
      {
        title: { pl: "Wizyta w kalendarzu", en: "The visit in the calendar" },
        href: "/panel/calendar?view=day&date=2026-10-06",
      },
    ],
    matched: ["name"],
    seen_in: ["bookings"],
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

function type(value: string) {
  fireEvent.change(
    screen.getByLabelText("Imię i nazwisko, e-mail albo telefon klienta"),
    { target: { value } },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.searchCustomers.mockResolvedValue({ total: 1, items: [customer()] });
  api.previewCustomerAnonymization.mockResolvedValue({
    id: ANNA,
    anonymized_at: null,
    kept: [],
  });
  api.anonymizeCustomer.mockResolvedValue({
    id: ANNA,
    anonymized_at: "2026-10-04T10:00:00Z",
  });
});

test("a customer with no order is found by what they gave and removed after the question", async () => {
  const { container } = wrap(<CustomerRemovalPanel />);
  const search = screen.getByRole("button", { name: "Szukaj" });
  // One letter is nobody's name: nothing is asked of the server.
  type("k");
  expect((search as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByRole("table")).toBeNull();

  type("  Kowalska ");
  fireEvent.click(search);
  const table = await screen.findByRole("table", {
    name: "Znalezieni klienci",
  });
  expect(api.searchCustomers).toHaveBeenCalledWith("Kowalska");
  expect(within(table).getByText("anna@example.test")).toBeTruthy();
  expect(
    within(table)
      .getByRole("link", { name: "Wizyta w kalendarzu" })
      .getAttribute("href"),
  ).toBe("/panel/calendar?view=day&date=2026-10-06");
  expect(await axe.run(container)).toMatchObject({ violations: [] });

  fireEvent.click(within(table).getByRole("button", { name: "Usuń dane…" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Usunąć dane klienta Anna Kowalska?",
  });
  expect(api.previewCustomerAnonymization).toHaveBeenCalledWith(ANNA);
  // No order of hers was paid for: nothing that names her stays.
  expect(
    await within(dialog).findByText(
      /Żadne zamówienie tego klienta nie ma wpłaty/,
    ),
  ).toBeTruthy();

  api.searchCustomers.mockResolvedValue({ total: 0, items: [] });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Usuń dane klienta" }),
  );
  await waitFor(() => expect(api.anonymizeCustomer).toHaveBeenCalledWith(ANNA));
  expect(
    await screen.findByText("Dane klienta Anna Kowalska zostały usunięte."),
  ).toBeTruthy();
  // The search is read again: the person is gone from it too.
  await waitFor(() => expect(api.searchCustomers).toHaveBeenCalledTimes(2));
  expect(
    await screen.findByText(/Nie znaleziono klienta pasującego do „Kowalska”/),
  ).toBeTruthy();
});

test("more matches than shown are said, a failed search too, and the contact only where the reader sees it", async () => {
  api.searchCustomers.mockResolvedValue({
    total: 14,
    items: [customer({ email: null, phone: null })],
  });
  wrap(<CustomerRemovalPanel />, "en");
  fireEvent.change(
    screen.getByLabelText("The customer's name, e-mail or phone"),
    { target: { value: "Kowalska" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Search" }));

  expect(
    await screen.findByText(/Matching customers: 14\. Showing the first 1/),
  ).toBeTruthy();
  expect(screen.queryByText("anna@example.test")).toBeNull();
  expect(
    screen.getByRole("link", { name: "The visit in the calendar" }),
  ).toBeTruthy();

  api.searchCustomers.mockRejectedValue(new Error("offline"));
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
  expect((await screen.findByRole("alert")).textContent).toBe(
    "Could not search the customers. Try again.",
  );
});
