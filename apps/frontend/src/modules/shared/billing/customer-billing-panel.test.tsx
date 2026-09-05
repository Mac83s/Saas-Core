import axe from "axe-core";
import {
  act,
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
import { ApiProblemError } from "@saas-core/api-client";
import { CustomerBillingPanel } from "./customer-billing-panel";

const {
  activateBillingTrial,
  createBillingCheckout,
  createBillingPortal,
  getCustomerBillingOverview,
  searchParams,
} = vi.hoisted(() => ({
  activateBillingTrial: vi.fn(),
  createBillingCheckout: vi.fn(),
  createBillingPortal: vi.fn(),
  getCustomerBillingOverview: vi.fn(),
  searchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({ useSearchParams: () => searchParams }));
vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  activateBillingTrial,
  createBillingCheckout,
  createBillingPortal,
  getCustomerBillingOverview,
}));

const overview = {
  can_manage: true,
  payment_mode: "simulated" as const,
  portal_available: false,
  has_active_subscription: false,
  billing_details: {
    customer_kind: "company" as const,
    legal_name: "Firma testowa",
    tax_id: "",
    country_code: "PL",
    address_line1: "Testowa 1",
    postal_code: "00-001",
    city: "Warszawa",
    billing_email: "faktury@example.test",
    missing: [] as string[],
  },
  subscription: null,
  plans: [
    {
      key: "profile",
      name: "Profil",
      description: "Opis z bazy",
      version: 1,
      currency: "PLN",
      billing_interval: "month",
      unit_amount_minor: 9_900,
      trial_days: 14,
      features: ["sites.enabled"],
      quotas: {
        "sites.max": 1,
        "locations.max": 1,
        "appointments.monthly": 250,
      },
      is_current: false,
      checkout_available: true,
    },
    {
      key: "starter",
      name: "Starter",
      description: "Opis z bazy",
      version: 1,
      currency: "PLN",
      billing_interval: "month",
      unit_amount_minor: 14_900,
      trial_days: 3,
      features: ["sites.enabled"],
      quotas: {
        "sites.max": 1,
        "locations.max": 1,
        "appointments.monthly": 1_000,
      },
      is_current: false,
      checkout_available: true,
    },
    {
      key: "pro",
      name: "Pro",
      description: "Opis z bazy",
      version: 1,
      currency: "PLN",
      billing_interval: "month",
      unit_amount_minor: 29_900,
      trial_days: 3,
      features: ["sites.enabled", "custom_domain.enabled"],
      quotas: {
        "sites.max": 3,
        "locations.max": 5,
        "appointments.monthly": 10_000,
      },
      is_current: false,
      checkout_available: true,
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  searchParams.delete("checkout");
  searchParams.delete("session_id");
  getCustomerBillingOverview.mockResolvedValue(overview);
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

test.each([
  [
    "pl",
    polishMessages,
    "Porównaj plany",
    "Profil",
    "Demonstracyjny tryb płatności",
    "Symuluj wybór planu",
  ],
  [
    "en",
    englishMessages,
    "Compare plans",
    "Profile",
    "Demo payment mode",
    "Simulate plan selection",
  ],
] as const)(
  "renderuje dostępny katalog planów w locale %s",
  async (
    locale,
    messages,
    heading,
    profileName,
    simulationTitle,
    simulationAction,
  ) => {
    const rendered = render(
      <NextIntlClientProvider locale={locale} messages={messages}>
        <CustomerBillingPanel />
      </NextIntlClientProvider>,
    );

    expect(
      await screen.findByRole("heading", { name: heading }),
    ).not.toBeNull();
    expect(screen.getByRole("heading", { name: profileName })).not.toBeNull();
    expect(
      screen.getByRole("complementary", { name: simulationTitle }),
    ).not.toBeNull();
    expect(
      screen.getAllByRole("button", { name: simulationAction }),
    ).toHaveLength(3);
    expect(screen.queryByText("Opis z bazy")).toBeNull();
    expect((await axe.run(rendered.container)).violations).toHaveLength(0);
  },
);

test("po błędzie nie udaje braku planu i pozwala ponowić odczyt", async () => {
  getCustomerBillingOverview.mockRejectedValueOnce(new Error("offline"));
  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <CustomerBillingPanel />
    </NextIntlClientProvider>,
  );

  expect(
    await screen.findByText(
      "Nie udało się pobrać informacji o planach. Spróbuj ponownie.",
    ),
  ).not.toBeNull();
  expect(screen.queryByText("Bez planu")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
  expect(
    await screen.findByRole("heading", { name: "Porównaj plany" }),
  ).not.toBeNull();
  expect(getCustomerBillingOverview).toHaveBeenCalledTimes(2);
});

test("po opóźnionym callbacku ponawia aktywację i ogłasza sukces z focusem", async () => {
  searchParams.set("checkout", "success");
  searchParams.set("session_id", "cs_callback");
  activateBillingTrial.mockRejectedValue(checkoutPendingProblem());

  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <CustomerBillingPanel />
    </NextIntlClientProvider>,
  );

  const activateButton = await screen.findByRole("button", {
    name: "Rozpocznij okres próbny",
  });
  const callbackHeading = screen.getByRole("heading", {
    name: "Wybór planu został zasymulowany",
  });
  expect(callbackHeading).not.toBeNull();
  expect(
    screen.getByText(
      "Potwierdź uruchomienie okresu próbnego w demonstracyjnym trybie.",
    ),
  ).not.toBeNull();
  expect(
    callbackHeading.closest('[data-slot="card"]')?.textContent,
  ).not.toMatch(/Stripe|obciąż/i);
  vi.useFakeTimers();
  fireEvent.click(activateButton);
  await act(async () => {
    await vi.runAllTimersAsync();
  });
  vi.useRealTimers();

  expect(activateBillingTrial).toHaveBeenCalledTimes(4);
  for (const call of activateBillingTrial.mock.calls) {
    expect(call[0]).toBe("cs_callback");
  }

  activateBillingTrial.mockResolvedValue({
    id: "019ff20d-a000-7000-8000-000000000010",
    status: "trialing",
    created: true,
  });
  getCustomerBillingOverview.mockResolvedValue({
    ...overview,
    subscription: {
      state: "trialing",
      access_mode: "full",
      plan_key: "profile",
      plan_version: 1,
      current_period_end: "2026-08-27T12:00:00Z",
      trial_end: "2026-08-27T12:00:00Z",
      grace_period_end: null,
      cancel_at_period_end: false,
    },
  });

  fireEvent.click(
    screen.getByRole("button", { name: "Spróbuj aktywować ponownie" }),
  );

  const success = await screen.findByRole("status");
  expect(success.textContent).toContain("Okres próbny został uruchomiony");
  expect(activateBillingTrial).toHaveBeenCalledTimes(5);
  await waitFor(() => expect(document.activeElement).toBe(success));
});

test("w symulacji ukrywa portal i blokuje zmianę aktywnego planu", async () => {
  getCustomerBillingOverview.mockResolvedValue({
    ...overview,
    portal_available: true,
    has_active_subscription: true,
    subscription: {
      state: "trialing",
      access_mode: "full",
      plan_key: "profile",
      plan_version: 1,
      current_period_end: "2026-08-27T12:00:00Z",
      trial_end: "2026-08-27T12:00:00Z",
      grace_period_end: null,
      cancel_at_period_end: false,
    },
    plans: overview.plans.map((plan) => ({
      ...plan,
      is_current: plan.key === "profile",
    })),
  });

  const rendered = render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <CustomerBillingPanel />
    </NextIntlClientProvider>,
  );

  expect(
    await screen.findByRole("heading", { name: "Porównaj plany" }),
  ).not.toBeNull();
  expect(
    screen.queryByRole("button", {
      name: "Zarządzaj płatnością i planem",
    }),
  ).toBeNull();
  const lockedPlans = screen.getAllByRole("button", {
    name: "Plan jest już aktywny w wersji demo",
  });
  expect(lockedPlans).toHaveLength(2);
  for (const button of lockedPlans) expect(button).toBeDisabled();
  expect(createBillingPortal).not.toHaveBeenCalled();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("po zakończonym trialu znów pozwala wybrać plan", async () => {
  // The panel used to read the mere presence of a subscription payload as
  // "already subscribed". That payload also describes a canceled plan, so an
  // organization whose trial ended saw three disabled buttons and had no way
  // to buy anything — while the API would have accepted the checkout.
  getCustomerBillingOverview.mockResolvedValue({
    ...overview,
    has_active_subscription: false,
    subscription: {
      state: "canceled",
      access_mode: "full",
      plan_key: "profile",
      plan_version: 1,
      current_period_end: "2026-08-24T12:00:00Z",
      trial_end: "2026-08-24T12:00:00Z",
      grace_period_end: null,
      cancel_at_period_end: false,
    },
    plans: overview.plans.map((plan) => ({
      ...plan,
      is_current: plan.key === "profile",
    })),
  });

  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <CustomerBillingPanel />
    </NextIntlClientProvider>,
  );

  const choose = await screen.findAllByRole("button", {
    name: "Symuluj wybór planu",
  });
  expect(choose).toHaveLength(2);
  for (const button of choose) expect(button).not.toBeDisabled();
  expect(
    screen.queryByRole("button", {
      name: "Plan jest już aktywny w wersji demo",
    }),
  ).toBeNull();
});

test("bez danych do faktury nie da się kliknąć planu", async () => {
  // Stripe Tax cannot price anything without an address, so the API would
  // answer 409. The panel says so before the click instead of after it.
  getCustomerBillingOverview.mockResolvedValue({
    ...overview,
    billing_details: {
      ...overview.billing_details,
      address_line1: "",
      postal_code: "",
      city: "",
      missing: ["address_line1", "postal_code", "city"],
    },
  });

  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <CustomerBillingPanel />
    </NextIntlClientProvider>,
  );

  const blocked = await screen.findAllByRole("button", {
    name: "Najpierw uzupełnij dane do faktury",
  });
  expect(blocked).toHaveLength(3);
  for (const button of blocked) expect(button).toBeDisabled();
  expect(
    screen.getByText("Uzupełnij dane do faktury, żeby móc wybrać plan."),
  ).not.toBeNull();
});

function checkoutPendingProblem() {
  return new ApiProblemError({
    type: "about:blank",
    title: "Conflict",
    status: 409,
    code: "completed_checkout_required",
    detail: "Stripe is still confirming the completed checkout.",
    correlation_id: null,
  });
}

test("z aktywnym planem kieruje zmianę planu do portalu Stripe", async () => {
  // Zmiana planu należy do portalu (ADR-040), bo proratę i fakturę korygującą
  // liczy Stripe. Panel ma tam zaprowadzić, a nie próbować drugiego zakupu.
  const original = Object.getOwnPropertyDescriptor(window, "location");
  const assign = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, assign },
  });
  createBillingPortal.mockResolvedValue({
    id: "bps_1",
    url: "https://billing.stripe.test/session",
    expires_at: null,
  });
  getCustomerBillingOverview.mockResolvedValue({
    ...overview,
    payment_mode: "stripe" as const,
    portal_available: true,
    has_active_subscription: true,
    subscription: {
      state: "active",
      access_mode: "full",
      plan_key: "profile",
      plan_version: 1,
      current_period_end: "2026-10-04T12:00:00Z",
      trial_end: null,
      grace_period_end: null,
      cancel_at_period_end: false,
    },
    plans: overview.plans.map((plan) => ({
      ...plan,
      is_current: plan.key === "profile",
    })),
  });

  try {
    render(
      <NextIntlClientProvider locale="pl" messages={polishMessages}>
        <CustomerBillingPanel />
      </NextIntlClientProvider>,
    );

    const upgrade = await screen.findAllByRole("button", {
      name: "Zmień plan w portalu płatności",
    });
    expect(upgrade).toHaveLength(2);
    fireEvent.click(upgrade[0]!);

    await waitFor(() => expect(createBillingPortal).toHaveBeenCalledTimes(1));
    expect(createBillingCheckout).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith(
        "https://billing.stripe.test/session",
      ),
    );
  } finally {
    if (original) Object.defineProperty(window, "location", original);
  }
});
