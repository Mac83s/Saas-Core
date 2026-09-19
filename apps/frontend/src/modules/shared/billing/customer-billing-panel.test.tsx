import axe from "axe-core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import {
  ApiProblemError,
  type CustomerBillingOverview,
  type CustomerSubscription,
} from "@saas-core/api-client";
import { CustomerBillingPanel } from "./customer-billing-panel";

const {
  activateBillingTrial,
  createBillingCheckout,
  createBillingPortal,
  getCustomerBillingOverview,
  updateBillingDetails,
  searchParams,
} = vi.hoisted(() => ({
  activateBillingTrial: vi.fn(),
  createBillingCheckout: vi.fn(),
  createBillingPortal: vi.fn(),
  getCustomerBillingOverview: vi.fn(),
  updateBillingDetails: vi.fn(),
  searchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({ useSearchParams: () => searchParams }));
vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  activateBillingTrial,
  createBillingCheckout,
  createBillingPortal,
  getCustomerBillingOverview,
  updateBillingDetails,
}));

const DAY = 24 * 60 * 60 * 1000;
const FEATURES = {
  pl: {
    "sites.enabled": "Strona internetowa",
    "custom_domain.enabled": "Własna domena",
  },
  en: { "sites.enabled": "Website", "custom_domain.enabled": "Custom domain" },
};

const overview: CustomerBillingOverview = {
  can_manage: true,
  payment_mode: "simulated",
  portal_available: false,
  has_active_subscription: false,
  billing_details: {
    customer_kind: "company",
    legal_name: "Firma testowa",
    tax_id: "",
    country_code: "PL",
    address_line1: "Testowa 1",
    postal_code: "00-001",
    city: "Warszawa",
    billing_email: "faktury@example.test",
    missing: [],
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
        "storage.bytes": 5 * 1024 ** 3,
      },
      is_current: false,
      checkout_available: true,
    },
  ],
};

/** An organization on the Profile plan, in the given subscription state. */
function subscribed(
  subscription: Partial<CustomerSubscription>,
  extra: Partial<CustomerBillingOverview> = {},
): CustomerBillingOverview {
  return {
    ...overview,
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
      ...subscription,
    },
    plans: overview.plans.map((plan) => ({
      ...plan,
      is_current: plan.key === "profile",
    })),
    ...extra,
  };
}

function renderPanel(locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
    >
      <CustomerBillingPanel featureLabels={FEATURES[locale]} />
    </NextIntlClientProvider>,
  );
}

function planCard(name: string) {
  return screen.getByRole("heading", { name }).closest("li")!;
}

/** Stands in for window.location so a redirect can be observed. */
async function withLocation(
  run: (assign: ReturnType<typeof vi.fn>) => Promise<void>,
) {
  const original = Object.getOwnPropertyDescriptor(window, "location");
  const assign = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, assign },
  });
  try {
    await run(assign);
  } finally {
    if (original) Object.defineProperty(window, "location", original);
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  for (const key of ["checkout", "session_id", "feature"])
    searchParams.delete(key);
  getCustomerBillingOverview.mockResolvedValue(overview);
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

test.each([
  [
    "pl",
    "Porównaj plany",
    ["Profil", "Witryna", "Pro"],
    "Demonstracyjny tryb płatności",
    "Symuluj wybór planu",
    "Rezerwacje w miesiącu",
    ["250", "1000", "10 000"],
    /nie ma w planie/,
  ],
  [
    "en",
    "Compare plans",
    ["Profile", "Website", "Pro"],
    "Demo payment mode",
    "Simulate plan selection",
    "Bookings per month",
    ["250", "1,000", "10,000"],
    /not included/,
  ],
] as const)(
  "porównuje plany wiersz po wierszu w locale %s",
  async (
    locale,
    heading,
    names,
    simulationTitle,
    simulationAction,
    bookingsRow,
    bookings,
    notIncluded,
  ) => {
    const rendered = renderPanel(locale);

    expect(
      await screen.findByRole("heading", { name: heading }),
    ).not.toBeNull();
    expect(
      screen.getByRole("complementary", { name: simulationTitle }),
    ).not.toBeNull();
    expect(
      screen.getAllByRole("button", { name: simulationAction }),
    ).toHaveLength(3);
    // The same limit rows in every card, a dash where a plan has none.
    expect(screen.getAllByText(bookingsRow)).toHaveLength(3);
    names.forEach((name, index) =>
      expect(within(planCard(name)).getByText(bookings[index]!)).not.toBeNull(),
    );
    const [profile, , pro] = names.map(planCard);
    expect(within(profile!).getByText("—")).not.toBeNull();
    expect(within(pro!).getByText("5 GB")).not.toBeNull();
    // The domain row is in every card; only where the plan lacks it does a
    // screen reader hear so.
    expect(within(profile!).getByText(notIncluded)).not.toBeNull();
    expect(within(pro!).queryByText(notIncluded)).toBeNull();
    expect(screen.queryByText("Opis z bazy")).toBeNull();
    expect((await axe.run(rendered.container)).violations).toHaveLength(0);
  },
);

test("po błędzie nie udaje braku planu i pozwala ponowić odczyt", async () => {
  getCustomerBillingOverview.mockRejectedValueOnce(new Error("offline"));
  renderPanel();

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

test("bez uprawnienia mówi dlaczego i nie proponuje ponowienia", async () => {
  getCustomerBillingOverview.mockRejectedValueOnce(
    problem(403, "organization_permission_denied"),
  );
  renderPanel();

  expect(
    await screen.findByText(
      "Nie masz uprawnienia do zarządzania płatnościami tej firmy.",
    ),
  ).not.toBeNull();
  expect(screen.queryByRole("button", { name: "Spróbuj ponownie" })).toBeNull();
});

test("po opóźnionym callbacku ponawia aktywację i ogłasza sukces z focusem", async () => {
  searchParams.set("checkout", "success");
  searchParams.set("session_id", "cs_callback");
  activateBillingTrial.mockRejectedValue(
    problem(409, "completed_checkout_required"),
  );

  renderPanel();

  const activateButton = await screen.findByRole("button", {
    name: "Rozpocznij okres próbny",
  });
  const callbackHeading = screen.getByRole("heading", {
    name: "Wybór planu został zasymulowany",
  });
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
  getCustomerBillingOverview.mockResolvedValue(
    subscribed({ state: "trialing", trial_end: "2026-08-27T12:00:00Z" }),
  );

  fireEvent.click(
    screen.getByRole("button", { name: "Spróbuj aktywować ponownie" }),
  );

  const success = await screen.findByRole("status");
  expect(success.textContent).toContain("Okres próbny został uruchomiony");
  expect(activateBillingTrial).toHaveBeenCalledTimes(5);
  await waitFor(() => expect(document.activeElement).toBe(success));
});

test("firma po wcześniejszym planie aktywuje plan bez obietnicy okresu próbnego", async () => {
  // A free trial is granted once per organization; the API starts a paid plan
  // for anyone who had one before, so the panel must not promise otherwise.
  searchParams.set("checkout", "success");
  searchParams.set("session_id", "cs_again");
  getCustomerBillingOverview.mockResolvedValue({
    ...subscribed({ state: "canceled" }),
    has_active_subscription: false,
  });

  renderPanel();

  expect(
    await screen.findByRole("button", { name: "Aktywuj plan" }),
  ).not.toBeNull();
  expect(screen.queryByText(/bezpłatnego okresu próbnego/)).toBeNull();
});

test("w symulacji ukrywa portal, blokuje zmianę planu i liczy dni okresu próbnego", async () => {
  getCustomerBillingOverview.mockResolvedValue(
    subscribed(
      {
        state: "trialing",
        trial_end: new Date(
          Date.now() + 5 * DAY + 60 * 60 * 1000,
        ).toISOString(),
      },
      { portal_available: true },
    ),
  );

  const rendered = renderPanel();

  expect(await screen.findByText("Okres próbny: zostało 5 dni")).not.toBeNull();
  expect(
    screen.getByText("W trybie demonstracyjnym nic nie zostanie pobrane."),
  ).not.toBeNull();
  expect(
    screen.queryByRole("button", { name: /Zarządzaj płatnością/ }),
  ).toBeNull();
  const lockedPlans = screen.getAllByRole("button", {
    name: "Plan jest już aktywny w wersji demo",
  });
  expect(lockedPlans).toHaveLength(2);
  for (const button of lockedPlans) expect(button).toBeDisabled();
  expect(
    within(planCard("Profil")).getByRole("button", { name: "Bieżący plan" }),
  ).toBeDisabled();
  expect(createBillingPortal).not.toHaveBeenCalled();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("po zakończonym planie znów pozwala wybrać każdy plan, także poprzedni", async () => {
  // The panel used to read the mere presence of a subscription payload as
  // "already subscribed", and then the snapshot's plan as "current". Both
  // describe a canceled plan too, and the API sells it again — so an
  // organization whose plan ended must be able to buy any plan, its last one
  // included.
  getCustomerBillingOverview.mockResolvedValue({
    ...subscribed({ state: "canceled", current_period_end: null }),
    has_active_subscription: false,
  });

  renderPanel();

  const choose = await screen.findAllByRole("button", {
    name: "Symuluj wybór planu",
  });
  expect(choose).toHaveLength(3);
  for (const button of choose) expect(button).not.toBeDisabled();
  expect(screen.getByText("Plan został anulowany")).not.toBeNull();
  expect(
    screen.queryByRole("button", {
      name: "Plan jest już aktywny w wersji demo",
    }),
  ).toBeNull();
});

test("bez danych do faktury nie da się kliknąć planu, a formularz jest otwarty", async () => {
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

  renderPanel();

  const blocked = await screen.findAllByRole("button", {
    name: "Najpierw uzupełnij dane do faktury",
  });
  expect(blocked).toHaveLength(3);
  for (const button of blocked) expect(button).toBeDisabled();
  expect(
    screen.getByText("Uzupełnij dane do faktury, żeby móc wybrać plan."),
  ).not.toBeNull();
  expect(screen.getByRole("textbox", { name: "Ulica i numer" })).not.toBeNull();
  expect(screen.queryByRole("button", { name: "Anuluj" })).toBeNull();
});

test("komplet danych do faktury to podsumowanie, a edycja wraca do niego z focusem", async () => {
  updateBillingDetails.mockImplementation(async (details: object) => ({
    ...details,
    missing: [],
  }));
  const rendered = renderPanel();

  expect(await screen.findByText("Firma · Firma testowa")).not.toBeNull();
  expect(screen.getByText("Testowa 1, 00-001 Warszawa, Polska")).not.toBeNull();
  expect(screen.queryByRole("textbox", { name: "Ulica i numer" })).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "Zmień dane" }));
  const name = screen.getByRole("textbox", {
    name: "Nazwa firmy albo imię i nazwisko",
  });
  await waitFor(() => expect(document.activeElement).toBe(name));
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);

  fireEvent.change(name, { target: { value: "Nowa nazwa" } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz dane" }));

  await waitFor(() =>
    expect(updateBillingDetails).toHaveBeenCalledWith({
      customer_kind: "company",
      legal_name: "Nowa nazwa",
      tax_id: "",
      country_code: "PL",
      address_line1: "Testowa 1",
      postal_code: "00-001",
      city: "Warszawa",
      billing_email: "faktury@example.test",
    }),
  );
  expect(await screen.findByText("Firma · Nowa nazwa")).not.toBeNull();
  expect(screen.getByRole("status").textContent).toBe(
    "Dane do faktury zapisane.",
  );
  await waitFor(() =>
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Zmień dane" }),
    ),
  );
});

test("z aktywnym planem pokazuje następną płatność i kieruje zmianę planu do portalu", async () => {
  // Zmiana planu należy do portalu (ADR-040), bo proratę i fakturę korygującą
  // liczy Stripe. Panel ma tam zaprowadzić, a nie próbować drugiego zakupu.
  createBillingPortal.mockResolvedValue({
    id: "bps_1",
    url: "https://billing.stripe.test/session",
    expires_at: null,
  });
  getCustomerBillingOverview.mockResolvedValue(
    subscribed({}, { payment_mode: "stripe", portal_available: true }),
  );

  await withLocation(async (assign) => {
    renderPanel();

    expect(await screen.findByText("Następna płatność")).not.toBeNull();
    expect(screen.getByText("4 paź 2026 · 99 zł netto")).not.toBeNull();
    expect(
      screen.getByText(
        "Metoda płatności, historia faktur i anulowanie planu są w portalu operatora płatności.",
      ),
    ).not.toBeNull();
    const upgrade = screen.getAllByRole("button", {
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
  });
});

test("nieudana płatność mówi, do kiedy trwa karencja, i prowadzi do portalu", async () => {
  createBillingPortal.mockResolvedValue({
    id: "bps_2",
    url: "https://billing.stripe.test/update",
    expires_at: null,
  });
  getCustomerBillingOverview.mockResolvedValue(
    subscribed(
      { state: "grace_period", grace_period_end: "2026-10-10T12:00:00Z" },
      { payment_mode: "stripe", portal_available: true },
    ),
  );

  await withLocation(async (assign) => {
    const rendered = renderPanel();

    expect(await screen.findByText("Płatność się nie powiodła")).not.toBeNull();
    expect(
      screen.getByText(
        "Zaktualizuj metodę płatności do 10 paź 2026, żeby zachować pełny dostęp. Potem konto przejdzie w tryb tylko do odczytu — dane zostaną zachowane.",
      ),
    ).not.toBeNull();
    expect(screen.getByText("Pełny dostęp do")).not.toBeNull();
    expect((await axe.run(rendered.container)).violations).toHaveLength(0);

    fireEvent.click(
      screen.getByRole("button", { name: "Zaktualizuj metodę płatności" }),
    );
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("https://billing.stripe.test/update"),
    );
  });
});

test("plan anulowany na koniec okresu mówi, kiedy wygaśnie, bez następnej płatności", async () => {
  getCustomerBillingOverview.mockResolvedValue(
    subscribed(
      { cancel_at_period_end: true },
      { payment_mode: "stripe", portal_available: true },
    ),
  );

  renderPanel();

  expect(await screen.findByText("Plan wygaśnie 4 paź 2026")).not.toBeNull();
  expect(
    screen.getByText(
      "Do tego dnia wszystko działa bez zmian. Plan możesz wznowić w portalu płatności.",
    ),
  ).not.toBeNull();
  expect(screen.getByText("wygasa z końcem okresu")).not.toBeNull();
  expect(screen.getByText("Plan wygasa")).not.toBeNull();
  expect(screen.queryByText("Następna płatność")).toBeNull();
});

test("okres próbny ze Stripe pokazuje pierwszą płatność", async () => {
  getCustomerBillingOverview.mockResolvedValue(
    subscribed(
      {
        state: "trialing",
        trial_end: "2026-10-02T12:00:00Z",
        current_period_end: "2026-10-02T12:00:00Z",
      },
      { payment_mode: "stripe", portal_available: true },
    ),
  );

  renderPanel();

  expect(await screen.findByText("Pierwsza płatność")).not.toBeNull();
  expect(screen.getByText("2 paź 2026 · 99 zł netto")).not.toBeNull();
  expect(screen.getByText("Okres próbny do")).not.toBeNull();
  expect(
    screen.getByRole("button", { name: "Zarządzaj płatnością" }),
  ).not.toBeNull();
});

test("odesłanie po brakującą funkcję wskazuje plan, który ją ma", async () => {
  searchParams.set("feature", "custom_domain.enabled");
  getCustomerBillingOverview.mockResolvedValue(
    subscribed({}, { payment_mode: "stripe", portal_available: true }),
  );

  renderPanel();

  expect(
    await screen.findByText("Twój plan nie obejmuje funkcji: Własna domena"),
  ).not.toBeNull();
  expect(
    within(planCard("Pro")).getByText("Zawiera tę funkcję"),
  ).not.toBeNull();
  expect(within(planCard("Profil")).getByText("Twój plan")).not.toBeNull();
});

test("osoba bez prawa zakupu widzi dane do faktury tylko do odczytu", async () => {
  getCustomerBillingOverview.mockResolvedValue({
    ...overview,
    can_manage: false,
  });

  renderPanel();

  expect(
    await screen.findByText("Dane do faktury zmienia właściciel firmy."),
  ).not.toBeNull();
  expect(screen.queryByRole("button", { name: "Zmień dane" })).toBeNull();
  for (const button of screen.getAllByRole("button", {
    name: "Tylko właściciel może wybrać plan",
  }))
    expect(button).toBeDisabled();
});

function problem(status: number, code: string) {
  return new ApiProblemError({
    type: "about:blank",
    title: "Problem",
    status,
    code,
    detail: "Problem from the API.",
    correlation_id: null,
  });
}
