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

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import type { CustomerCreditsOverview } from "@saas-core/api-client";
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

const overview: CustomerCreditsOverview = {
  can_buy: true,
  plan_required: false,
  payment_mode: "stripe",
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

function renderPanel(
  { canManageBilling = true, locale = "pl" } = {} as {
    canManageBilling?: boolean;
    locale?: "pl" | "en";
  },
) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
    >
      <CreditsPanel canManageBilling={canManageBilling} />
    </NextIntlClientProvider>,
  );
}

test.each([
  [
    "pl",
    "250 z 1000",
    "Odnawia się 30 wrz 2026",
    "Nie kupiłeś jeszcze żadnego pakietu.",
  ],
  [
    "en",
    "250 of 1000",
    "Renews on Sep 30, 2026",
    "You have not bought a pack yet.",
  ],
] as const)(
  "pokazuje saldo rozbite na pulę z planu i kupioną w locale %s",
  async (locale, allowance, renews, empty) => {
    const rendered = renderPanel({ locale });

    expect(await screen.findByText(allowance)).not.toBeNull();
    expect(screen.getByText(renews)).not.toBeNull();
    expect(screen.getByText(empty)).not.toBeNull();
    expect((await axe.run(rendered.container)).violations).toHaveLength(0);
  },
);

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

test("bez planu nie da się kupić, a właściciel dostaje drogę do planu", async () => {
  // The API refuses credits without a live plan and answers can_buy=false
  // for the owner too, so the button names the plan, not the role.
  getCustomerCredits.mockResolvedValue({
    ...overview,
    can_buy: false,
    plan_required: true,
  });

  renderPanel();

  const button = await screen.findByRole("button", {
    name: "Wymaga aktywnego planu",
  });
  expect(button).toBeDisabled();
  expect(
    screen.getByText("Kredyty są dodatkiem do aktywnego planu."),
  ).not.toBeNull();
  expect(
    screen.getByRole("link", { name: "Wybierz plan" }).getAttribute("href"),
  ).toBe("/panel/settings/billing");
});

test("bez planu pozostali członkowie zespołu dostają prośbę do właściciela", async () => {
  getCustomerCredits.mockResolvedValue({
    ...overview,
    can_buy: false,
    plan_required: true,
  });

  renderPanel({ canManageBilling: false });

  expect(
    await screen.findByText("Poproś właściciela firmy o wybranie planu."),
  ).not.toBeNull();
  expect(screen.queryByRole("link", { name: "Wybierz plan" })).toBeNull();
});

test("z planem kupuje tylko właściciel", async () => {
  getCustomerCredits.mockResolvedValue({ ...overview, can_buy: false });

  renderPanel({ canManageBilling: false });

  expect(
    await screen.findByRole("button", {
      name: "Tylko właściciel może kupować",
    }),
  ).toBeDisabled();
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

test("po błędzie odczytu pozwala spróbować ponownie", async () => {
  getCustomerCredits.mockRejectedValueOnce(new Error("offline"));

  renderPanel();

  expect(
    await screen.findByText("Nie udało się wczytać kredytów."),
  ).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
  expect(await screen.findByText("250 z 1000")).not.toBeNull();
  expect(getCustomerCredits).toHaveBeenCalledTimes(2);
});

test("historia pokazuje stan zakupów i pozwala dokończyć płatność", async () => {
  getCustomerCredits.mockResolvedValue({
    ...overview,
    payment_mode: "simulated",
    purchases: [
      {
        id: "019ff20d-a000-7000-8000-000000000020",
        pack_key: "credits-500",
        credits: 500,
        currency: "PLN",
        unit_amount_minor: 19_900,
        status: "pending",
        checkout_url: "https://checkout.stripe.test/cs_pending",
        created_at: "2026-09-12T10:00:00Z",
        completed_at: null,
      },
      {
        id: "019ff20d-a000-7000-8000-000000000021",
        pack_key: "credits-500",
        credits: 500,
        currency: "PLN",
        unit_amount_minor: 19_900,
        status: "succeeded",
        checkout_url: "",
        created_at: "2026-09-01T10:00:00Z",
        completed_at: "2026-09-01T10:01:00Z",
      },
    ],
  });

  renderPanel();

  expect(await screen.findByText("Oczekuje")).not.toBeNull();
  expect(screen.getByText("Opłacony")).not.toBeNull();
  expect(screen.getAllByText("500 kredytów").length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText("12 wrz 2026 · 199 zł")).not.toBeNull();
  expect(
    screen.getByRole("link", { name: "Dokończ płatność" }).getAttribute("href"),
  ).toBe("https://checkout.stripe.test/cs_pending");
  expect(
    screen.getByRole("complementary", {
      name: "Demonstracyjny tryb płatności",
    }),
  ).not.toBeNull();
});
