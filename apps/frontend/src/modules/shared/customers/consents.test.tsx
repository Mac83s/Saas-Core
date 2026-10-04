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

import { ApiProblemError, type MarketingConsent } from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { MarketingConsentsPanel } from "./consents-panel";

const { api } = vi.hoisted(() => ({
  api: {
    listMarketingConsents: vi.fn(),
    withdrawMarketingConsent: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

function consent(overrides: Partial<MarketingConsent> = {}): MarketingConsent {
  return {
    customer_id: "0199a000-0000-7000-8000-0000000000c1",
    name: "Anna Kowalska",
    email: "anna@example.test",
    phone: "+48 600 100 200",
    granted: true,
    consent_id: "0199a000-0000-7000-8000-0000000000e1",
    consented_at: "2026-10-04T08:30:00Z",
    source: "booking.appointment",
    source_reference: "0199a000-0000-7000-8000-0000000000a1",
    locale: "pl",
    wording: "Chcę otrzymywać oferty i promocje od Studio Fala e-mailem.",
    withdrawn_at: null,
    ...overrides,
  };
}

function page(items: MarketingConsent[]) {
  return { total: items.length, page: 1, page_size: 25, items };
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

beforeEach(() => {
  vi.clearAllMocks();
  api.listMarketingConsents.mockResolvedValue(page([consent()]));
});

test("the list says who agreed, when, on which form and to which words", async () => {
  const { container } = wrap(<MarketingConsentsPanel />);

  const table = await screen.findByRole("table", {
    name: "Zgody marketingowe klientów",
  });
  expect(api.listMarketingConsents).toHaveBeenCalledWith({
    state: "granted",
    page: 1,
    pageSize: 25,
  });
  expect(within(table).getByText("Anna Kowalska")).toBeTruthy();
  expect(
    within(table)
      .getByRole("link", { name: "anna@example.test" })
      .getAttribute("href"),
  ).toBe("mailto:anna@example.test");
  expect(within(table).getByText(/Formularz rezerwacji · PL/)).toBeTruthy();
  expect(
    within(table).getByText(
      "„Chcę otrzymywać oferty i promocje od Studio Fala e-mailem.”",
    ),
  ).toBeTruthy();
  expect(within(table).getByText("Zgoda aktualna")).toBeTruthy();
  // Read-only for whoever may not write a withdrawal down.
  expect(
    screen.queryByRole("button", { name: "Odnotuj wycofanie" }),
  ).toBeNull();
  expect(await axe.run(container)).toMatchObject({ violations: [] });
});

test("a consent from before the journal kept the words says they were not recorded, and nobody yet is said calmly", async () => {
  api.listMarketingConsents.mockResolvedValue(
    page([consent({ wording: "", source: "shop.checkout" })]),
  );
  const first = wrap(<MarketingConsentsPanel />);
  expect(
    await screen.findByText(/Treść niezapisana — tę zgodę zapisano/),
  ).toBeTruthy();
  // A form this panel has no name for is shown by its key.
  expect(screen.getByText(/shop\.checkout/)).toBeTruthy();
  first.unmount();

  api.listMarketingConsents.mockResolvedValue(page([]));
  wrap(<MarketingConsentsPanel />, "en");
  expect(await screen.findByText(/Nobody has agreed yet/)).toBeTruthy();
});

test("a withdrawal is written down after a question and the list is read again", async () => {
  api.withdrawMarketingConsent.mockResolvedValue(
    consent({ granted: false, withdrawn_at: "2026-10-04T10:00:00Z" }),
  );
  wrap(<MarketingConsentsPanel canManage />);

  fireEvent.click(
    await screen.findByRole("button", { name: "Odnotuj wycofanie" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Odnotować, że Anna Kowalska wycofuje zgodę?",
  });
  expect(within(dialog).getByText(/Wpisu nie da się usunąć/)).toBeTruthy();
  api.listMarketingConsents.mockResolvedValue(page([]));
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Odnotuj wycofanie" }),
  );

  await waitFor(() =>
    expect(api.withdrawMarketingConsent).toHaveBeenCalledWith(
      "0199a000-0000-7000-8000-0000000000c1",
      "0199a000-0000-7000-8000-0000000000e1",
    ),
  );
  expect(
    await screen.findByText(
      "Odnotowano: Anna Kowalska nie chce już otrzymywać ofert i promocji.",
    ),
  ).toBeTruthy();
  expect(api.listMarketingConsents).toHaveBeenCalledTimes(2);

  // Who took the consent back is read with the other state of the filter.
  api.listMarketingConsents.mockResolvedValue(
    page([consent({ granted: false, withdrawn_at: "2026-10-04T10:00:00Z" })]),
  );
  fireEvent.change(screen.getByLabelText("Stan zgody"), {
    target: { value: "withdrawn" },
  });
  await waitFor(() =>
    expect(api.listMarketingConsents).toHaveBeenLastCalledWith({
      state: "withdrawn",
      page: 1,
      pageSize: 25,
    }),
  );
  expect(
    await screen.findByText("Zgoda wycofana", { selector: "span" }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Odnotuj wycofanie" }),
  ).toBeNull();
});

test("a consent that changed meanwhile is read again instead of written twice", async () => {
  api.withdrawMarketingConsent.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "consent_changed",
      status: 409,
      code: "consent_changed",
      detail: "",
      correlation_id: null,
    }),
  );
  wrap(<MarketingConsentsPanel canManage />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Odnotuj wycofanie" }),
  );
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Odnotuj wycofanie" }),
  );
  expect(
    await screen.findByText(/Ta zgoda zmieniła się w międzyczasie/),
  ).toBeTruthy();
  expect(api.listMarketingConsents).toHaveBeenCalledTimes(2);
});

test("a failed load can be tried again", async () => {
  api.listMarketingConsents.mockRejectedValueOnce(new Error("offline"));
  wrap(<MarketingConsentsPanel />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Spróbuj ponownie" }),
  );
  expect(
    await screen.findByRole("table", { name: "Zgody marketingowe klientów" }),
  ).toBeTruthy();
});
