import axe from "axe-core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import polishMessages from "../../../../messages/pl.json";
import { CreditsPanel } from "./credits-panel";

const { createCreditCheckout, getCustomerCredits, searchParams } = vi.hoisted(
  () => ({
    createCreditCheckout: vi.fn(),
    getCustomerCredits: vi.fn(),
    searchParams: new URLSearchParams(),
  }),
);

vi.mock("next/navigation", () => ({ useSearchParams: () => searchParams }));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));
vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  createCreditCheckout,
  getCustomerCredits,
}));

const overview = {
  can_buy: true,
  plan_required: false,
  payment_mode: "stripe" as const,
  balance: {
    available: 1250,
    allowance_remaining: 250,
    allowance_granted: 1000,
    allowance_period_end: "2026-09-30",
    purchased_remaining: 1000,
    reserved: 0,
  },
  packs: [
    {
      key: "credits-500",
      name: "500 kredytów",
      description: "Pakiet na dłuższą pracę",
      credits: 500,
      currency: "PLN",
      unit_amount_minor: 19_900,
      purchasable: true,
    },
  ],
  purchases: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  searchParams.delete("checkout");
  getCustomerCredits.mockResolvedValue(overview);
});

afterEach(cleanup);

function renderPanel() {
  return render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <CreditsPanel />
    </NextIntlClientProvider>,
  );
}

test("pokazuje saldo rozbite na pulę z planu i kupioną", async () => {
  const rendered = renderPanel();

  expect(await screen.findByText("1250")).not.toBeNull();
  expect(screen.getByText("250 z 1000")).not.toBeNull();
  expect(screen.getByText("Odnawia się 2026-09-30")).not.toBeNull();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("zakup pakietu prowadzi do płatności", async () => {
  const original = Object.getOwnPropertyDescriptor(window, "location");
  const assign = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, assign },
  });
  createCreditCheckout.mockResolvedValue({
    id: "cs_credits",
    url: "https://checkout.stripe.test/cs_credits",
    expires_at: null,
  });

  try {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Kup pakiet" }));

    await waitFor(() => expect(createCreditCheckout).toHaveBeenCalledTimes(1));
    expect(createCreditCheckout.mock.calls[0]?.[0]).toBe("credits-500");
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith(
        "https://checkout.stripe.test/cs_credits",
      ),
    );
  } finally {
    if (original) Object.defineProperty(window, "location", original);
  }
});

test("bez planu nie da się kupić i panel mówi dlaczego", async () => {
  getCustomerCredits.mockResolvedValue({
    ...overview,
    can_buy: false,
    plan_required: true,
  });

  renderPanel();

  const button = await screen.findByRole("button", {
    name: "Tylko właściciel może kupować",
  });
  expect(button).toBeDisabled();
  expect(
    screen.getByText("Kredyty są dodatkiem do aktywnego planu."),
  ).not.toBeNull();
});

test("pakiet bez ceny w tym trybie nie jest oferowany", async () => {
  getCustomerCredits.mockResolvedValue({
    ...overview,
    packs: [{ ...overview.packs[0]!, purchasable: false }],
  });

  renderPanel();

  const button = await screen.findByRole("button", {
    name: "Chwilowo niedostępny",
  });
  expect(button).toBeDisabled();
});
