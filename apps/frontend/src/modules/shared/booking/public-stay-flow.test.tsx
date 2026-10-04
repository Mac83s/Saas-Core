import axe from "axe-core";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type BookingPublicAppointment,
  type BookingPublicCatalog,
  type BookingPublicQuote,
} from "@saas-core/api-client";

import polishMessages from "../../../../messages/pl.json";
import { PublicBookingFlow } from "./public-booking-flow";

const { api } = vi.hoisted(() => ({
  api: {
    createPublicStay: vi.fn(),
    getPublicBookingCatalog: vi.fn(),
    getPublicBookingConsents: vi.fn(),
    getPublicStayEnds: vi.fn(),
    getPublicStayPlan: vi.fn(),
    getPublicStayStarts: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const STAY = "11111111-1111-4111-8111-111111111111";
const COTTAGES = "22222222-2222-4222-8222-222222222222";
const FLAT = "33333333-3333-4333-8333-333333333333";
const CHILD = "44444444-4444-4444-8444-444444444444";
const LINEN = "55555555-5555-4555-8555-555555555555";
const TERMS = "66666666-6666-4666-8666-666666666666";

const catalog = {
  locations: [],
  services: [],
  resources: [],
  teams: [],
  people: [],
  stays: [
    {
      id: STAY,
      name: "Pobyt nad jeziorem",
      public_slug: "pobyt-nad-jeziorem",
      range_unit: "night",
      range_start_local: "15:00:00",
      range_end_local: "11:00:00",
      confirmation: "instant",
      response_hours: 24,
      groups: [
        {
          id: COTTAGES,
          name: "Domek nad jeziorem",
          description: "Dwie sypialnie i taras.",
          capacity: 6,
          units: 2,
        },
      ],
      units: [
        {
          id: FLAT,
          name: "Apartament na piętrze",
          description: "",
          capacity: 2,
        },
      ],
    },
  ],
  participant_categories: [
    { id: CHILD, name: "Dziecko do 12 lat", counts_towards_capacity: true },
  ],
  extras: [
    {
      id: LINEN,
      service_id: STAY,
      name: "Pościel",
      basis: "per_person",
      mandatory: false,
      max_quantity: 1,
      unit_gross_minor: 3000,
    },
  ],
  currency: "PLN",
  timezone: "Europe/Warsaw",
  online: {
    paused: false,
    resume_on: null,
    horizon_days: 15,
    last_day: "2026-10-18",
    period_last_day: "2028-04-04",
    contact: "email",
  },
  locales: ["pl"],
  locale: "pl",
} as unknown as BookingPublicCatalog;

const quote: BookingPublicQuote = {
  currency: "PLN",
  lines: [
    {
      kind: "price",
      name: "Pobyt nad jeziorem",
      quantity: 3,
      gross_minor: 120000,
    },
    {
      kind: "extra",
      name: "Sprzątanie końcowe",
      quantity: 1,
      gross_minor: 15000,
    },
  ],
  gross_minor: 135000,
  security_deposit_minor: 50000,
  payment_policy: "deposit",
  prepayment: { kind: "deposit", amount_minor: 40500, transfer_due_days: 3 },
  cancellation: null,
  digest: "digest-1",
};

const plan = {
  starts_at: "2026-11-07T14:00:00Z",
  ends_at: "2026-11-10T10:00:00Z",
  length: 3,
  range_unit: "night",
  quote,
};

const booked = {
  id: "77777777-7777-4777-8777-777777777777",
  starts_at: plan.starts_at,
  ends_at: plan.ends_at,
  timezone: "Europe/Warsaw",
  service_name: "Pobyt nad jeziorem",
  location_name: "Nad jeziorem",
  time_model: "range",
  range_unit: "night",
  unit_name: "Domek 2",
  status: "pending_payment",
  hold_expires_at: "2026-10-07T10:00:00Z",
  payment: {
    kind: "deposit",
    number: "R/2026/0042",
    amount_minor: 40500,
    currency: "PLN",
    due_at: "2026-10-07T10:00:00Z",
    account_holder: "Dokumenty Demo",
    account_number: "PL61 1090 1014 0000 0712 1981 2874",
    bank_name: "Bank Testowy",
  },
  settlement: null,
  team_name: null,
  person_name: null,
  self_service_token: "bk_token",
  self_service: { reschedule: false, cancel: true, until: null },
  quote,
} as unknown as BookingPublicAppointment;

function problem(status: number, code: string, extra: object = {}) {
  return new ApiProblemError({
    type: "about:blank",
    title: "Problem",
    status,
    code,
    detail: "",
    correlation_id: null,
    ...extra,
  });
}

function show() {
  return render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <PublicBookingFlow publicSlug="dokumenty-demo" />
    </NextIntlClientProvider>,
  );
}

async function pickDates() {
  fireEvent.click(
    await screen.findByRole("radio", { name: /Domek nad jeziorem/ }),
  );
  await waitFor(() =>
    expect(screen.getByLabelText("Przyjazd")).not.toBeDisabled(),
  );
  fireEvent.change(screen.getByLabelText("Przyjazd"), {
    target: { value: "2026-11-07" },
  });
  await waitFor(() =>
    expect(screen.getByLabelText("Wyjazd")).not.toBeDisabled(),
  );
  fireEvent.change(screen.getByLabelText("Wyjazd"), {
    target: { value: "2026-11-10" },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getPublicBookingCatalog.mockResolvedValue(catalog);
  api.getPublicBookingConsents.mockResolvedValue({
    locale: "pl",
    documents: [
      {
        kind: "booking_terms",
        statement: "Akceptuję regulamin rezerwacji.",
        text_id: TERMS,
        version: 1,
        effective_from: "2026-10-01",
        url: "/pl/documents/regulamin",
      },
    ],
  });
  api.getPublicStayStarts.mockResolvedValue(["2026-11-07", "2026-11-14"]);
  api.getPublicStayEnds.mockResolvedValue(["2026-11-09", "2026-11-10"]);
  api.getPublicStayPlan.mockResolvedValue(plan);
  api.createPublicStay.mockResolvedValue(booked);
});

test("a company with stays only opens the stay form, which passes axe", async () => {
  const { container } = show();

  expect(
    await screen.findByRole("radio", { name: /Domek nad jeziorem/ }),
  ).toBeInTheDocument();
  // The catalogue is asked in the page's language.
  expect(api.getPublicBookingCatalog).toHaveBeenCalledWith(
    "dokumenty-demo",
    "pl",
  );
  expect(
    screen.getByText(/Zameldowanie od 15:00, wymeldowanie do 11:00/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("radio", { name: /Apartament na piętrze/ }),
  ).toBeInTheDocument();
  expect(screen.getByText(/do 6 osób/)).toBeInTheDocument();
  // Nothing is searched before the guest says what they book.
  expect(api.getPublicStayStarts).not.toHaveBeenCalled();
  const results = await axe.run(container);
  expect(results.violations).toEqual([]);
});

test("the days, the party and the extras go to the server, which answers the price", async () => {
  show();
  await pickDates();

  expect(api.getPublicStayStarts).toHaveBeenCalledWith(
    "dokumenty-demo",
    expect.objectContaining({ service_id: STAY, group_id: COTTAGES }),
  );
  expect(api.getPublicStayEnds).toHaveBeenCalledWith("dokumenty-demo", {
    service_id: STAY,
    group_id: COTTAGES,
    start: "2026-11-07",
  });
  // A departure says how long the stay is.
  expect(
    screen.getByRole("option", { name: /10 listopada — 3 noce/ }),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Dziecko do 12 lat"), {
    target: { value: "1" },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: /Pościel/ }));
  await waitFor(() =>
    expect(api.getPublicStayPlan).toHaveBeenLastCalledWith("dokumenty-demo", {
      service_id: STAY,
      group_id: COTTAGES,
      start_date: "2026-11-07",
      end_date: "2026-11-10",
      participants: [
        { category_id: null, count: 2 },
        { category_id: CHILD, count: 1 },
      ],
      extras: [{ extra_id: LINEN, quantity: 1 }],
      locale: "pl",
    }),
  );
  // The server's price: the lines, the total, the deposit and the prepayment.
  expect(await screen.findByText(/1350,00\szł/)).toBeInTheDocument();
  expect(screen.getByText(/Kaucja zwrotna: 500,00\szł/)).toBeInTheDocument();
  expect(screen.getByText(/Przedpłata: 405,00\szł/)).toBeInTheDocument();
});

test("a guest books at the price shown, with the documents accepted", async () => {
  show();
  await pickDates();
  await screen.findByText(/1350,00\szł/);
  fireEvent.change(screen.getByLabelText("Imię i nazwisko"), {
    target: { value: "Jan Gość" },
  });
  fireEvent.change(screen.getByLabelText("E-mail"), {
    target: { value: "jan@example.test" },
  });

  // Without the box nothing is sent, and the box says why.
  fireEvent.click(screen.getByRole("button", { name: "Zarezerwuj" }));
  expect(
    await screen.findByText("Zaznacz to pole, żeby zarezerwować."),
  ).toBeInTheDocument();
  expect(api.createPublicStay).not.toHaveBeenCalled();

  fireEvent.click(
    screen.getByRole("checkbox", { name: /Akceptuję regulamin/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Zarezerwuj" }));
  await waitFor(() => expect(api.createPublicStay).toHaveBeenCalledTimes(1));
  expect(api.createPublicStay.mock.calls[0][1]).toEqual({
    service_id: STAY,
    group_id: COTTAGES,
    start_date: "2026-11-07",
    end_date: "2026-11-10",
    participants: [{ category_id: null, count: 2 }],
    quote_digest: "digest-1",
    consents: { documents: [TERMS] },
    customer: {
      display_name: "Jan Gość",
      email: "jan@example.test",
      phone: "",
      locale: "pl",
    },
  });
  // The stay waits for its prepayment: the days, the cottage the server
  // picked and the transfer's details.
  expect(
    await screen.findByText("Rezerwacja czeka na wpłatę"),
  ).toBeInTheDocument();
  expect(screen.getByText(/7–10 listopada 2026 · 3 noce/)).toBeInTheDocument();
  expect(screen.getByText("Domek 2")).toBeInTheDocument();
  expect(screen.getByText("R/2026/0042")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Zobacz rezerwację lub zrezygnuj" }),
  ).toHaveAttribute("href", "/pl/booking/bk_token");
});

test("another price by now is shown and asked about, never booked", async () => {
  api.createPublicStay.mockRejectedValueOnce(
    problem(409, "quote_changed", {
      detail: {
        quote: { ...quote, gross_minor: 150000, digest: "digest-2" },
      },
    }),
  );
  show();
  await pickDates();
  await screen.findByText(/1350,00\szł/);
  fireEvent.change(screen.getByLabelText("Imię i nazwisko"), {
    target: { value: "Jan Gość" },
  });
  fireEvent.change(screen.getByLabelText("E-mail"), {
    target: { value: "jan@example.test" },
  });
  fireEvent.click(
    screen.getByRole("checkbox", { name: /Akceptuję regulamin/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Zarezerwuj" }));

  expect(await screen.findByText(/Cena zmieniła się/)).toBeInTheDocument();
  expect(screen.getByText(/1500,00\szł/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Zarezerwuj" }));
  await waitFor(() => expect(api.createPublicStay).toHaveBeenCalledTimes(2));
  expect(api.createPublicStay.mock.calls[1][1].quote_digest).toBe("digest-2");
});

test("what the server refuses is said in the guest's words", async () => {
  api.getPublicStayPlan.mockRejectedValue(
    problem(400, "invalid", {
      errors: [
        { field: "participants", code: "unit_capacity_exceeded", message: "x" },
      ],
    }),
  );
  show();
  await pickDates();

  expect(
    await screen.findByText("Za dużo osób: zmieści się najwyżej 6."),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Zarezerwuj" })).toBeDisabled();
});

test("visits and stays share „Usługa”: a stay opens its form, a visit the one by the hour", async () => {
  const VISIT = "88888888-8888-4888-8888-888888888888";
  api.getPublicBookingCatalog.mockResolvedValue({
    ...catalog,
    locations: [
      {
        id: "99999999-9999-4999-8999-999999999999",
        name: "Gabinet",
        public_slug: "gabinet",
      },
    ],
    services: [
      {
        id: VISIT,
        name: "Konsultacja",
        public_slug: "konsultacja",
        duration_minutes: 60,
        appointment_kind: "",
        confirmation: "instant",
        response_hours: 24,
        staff_choice: "none",
        team_ids: [],
        person_ids: [],
      },
    ],
  });
  show();

  // The form by the hour first, as before; „Usługa” names the stay too.
  const service = await screen.findByLabelText("Usługa");
  expect(screen.getByLabelText("Miejsce")).toBeInTheDocument();
  await screen.findByRole("option", { name: "Pobyt nad jeziorem" });
  fireEvent.change(service, { target: { value: STAY } });
  expect(
    await screen.findByRole("radio", { name: /Domek nad jeziorem/ }),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Miejsce")).not.toBeInTheDocument();
  // …and back: the visit is chosen in the form by the hour.
  fireEvent.change(screen.getByLabelText("Usługa"), {
    target: { value: VISIT },
  });
  expect(await screen.findByLabelText("Miejsce")).toBeInTheDocument();
  expect(screen.getByLabelText("Usługa")).toHaveValue(VISIT);
});
