import axe from "axe-core";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ComponentProps, ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type BookingExtra,
  type BookingPrice,
  type BookingQuote,
  type ParticipantCategory,
  type ServiceSetup,
} from "@saas-core/api-client";

import englishMessages from "../../../../../messages/en.json";
import polishMessages from "../../../../../messages/pl.json";
import { ExtrasList } from "./extras-list";
import { parseAmount } from "./money";
import { OfferPricesDialog } from "./offer-prices-dialog";
import { PanelQuote } from "./panel-quote";
import type { PriceBook } from "./price-book";
import { PriceList } from "./price-list";

const api = vi.hoisted(() => ({
  copyBookingPricesToNextYear: vi.fn(),
  createBookingExtra: vi.fn(),
  createBookingPrice: vi.fn(),
  createParticipantCategory: vi.fn(),
  deleteBookingPrice: vi.fn(),
  getBookingQuote: vi.fn(),
  updateBookingExtra: vi.fn(),
  updateBookingPrice: vi.fn(),
  updateParticipantCategory: vi.fn(),
  updateSetupService: vi.fn(),
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({
  Link: ({
    children,
    ...props
  }: ComponentProps<"a"> & { children: ReactNode }) => (
    <a {...props}>{children}</a>
  ),
}));

const VISIT = "11111111-1111-4111-8111-111111111111";
const STAY = "11111111-1111-4111-8111-222222222222";
const GROUP = "33333333-3333-4333-8333-333333333333";
const UNIT = "44444444-4444-4444-8444-444444444444";
const CHILD = "55555555-5555-4555-8555-555555555555";
const BASE = "66666666-6666-4666-8666-666666666661";
const WEEKEND = "66666666-6666-4666-8666-666666666662";
const NIGHT = "66666666-6666-4666-8666-666666666663";
const OWN = "66666666-6666-4666-8666-666666666664";
const noContrast = { rules: { "color-contrast": { enabled: false } } };

const offer = (given: Partial<ServiceSetup>): ServiceSetup => ({
  id: VISIT,
  name: "Konsultacja",
  appointment_kind: "",
  time_model: "slot",
  range_unit: "",
  range_start_local: null,
  range_end_local: null,
  group_ids: [],
  duration_minutes: 60,
  buffer_before_minutes: 0,
  buffer_after_minutes: 0,
  minimum_notice_minutes: 60,
  staff_count: 1,
  public_staff_choice: "none",
  slot_step_minutes: 5,
  online: true,
  payment_policy: "on_site",
  active: true,
  draft: false,
  preset_id: null,
  preset_version: null,
  staff_ids: [],
  location_ids: [],
  resource_ids: [],
  materials: [],
  takes_materials: false,
  version: 3,
  future_bookings: 0,
  ...given,
});
const visit = offer({});
const stay = offer({
  id: STAY,
  name: "Pobyt w domku",
  time_model: "range",
  range_unit: "night",
  duration_minutes: null,
  staff_count: 0,
  group_ids: [GROUP],
});
const setup = {
  services: [visit, stay],
  groups: [
    { id: GROUP, name: "Domki", description: "", active: true, version: 1 },
  ],
  resources: [
    {
      id: UNIT,
      name: "Domek 1",
      active: true,
      version: 1,
      group_id: GROUP,
      location_id: null,
      capacity: 6,
      description: "",
    },
  ],
};

const price = (given: Partial<BookingPrice>): BookingPrice => ({
  id: BASE,
  name: "",
  service_id: VISIT,
  group_id: null,
  resource_id: null,
  starts_on: null,
  ends_on: null,
  weekdays: [],
  local_from: null,
  local_to: null,
  basis: "per_booking",
  amount_minor: 15000,
  currency: "PLN",
  vat_code: "23",
  included_people: null,
  extra_person_amount_minor: null,
  extra_person_per_time_unit: false,
  category_prices: [],
  length_discounts: [],
  active: true,
  version: 1,
  ...given,
});
const child: ParticipantCategory = {
  id: CHILD,
  name: "Dziecko",
  counts_towards_capacity: true,
  active: true,
  version: 1,
};
const extra = (given: Partial<BookingExtra>): BookingExtra => ({
  id: "77777777-7777-4777-8777-777777777771",
  service_id: VISIT,
  name: "Nagranie spotkania",
  kind: "charge",
  basis: "per_booking",
  amount_minor: 3000,
  currency: "PLN",
  vat_code: "23",
  mandatory: false,
  max_quantity: 2,
  active: true,
  version: 1,
  ...given,
});
const book = (given: Partial<PriceBook> = {}): PriceBook => ({
  prices: [
    price({}),
    price({
      id: WEEKEND,
      name: "Weekend",
      amount_minor: 18000,
      weekdays: [5, 6],
      local_from: "10:00:00",
      local_to: "14:00:00",
    }),
    price({
      id: NIGHT,
      service_id: STAY,
      name: "Lato",
      starts_on: "2027-07-01",
      ends_on: "2027-08-31",
      basis: "per_time_unit",
      amount_minor: 50000,
      vat_code: "8",
      included_people: 4,
      extra_person_amount_minor: 6000,
      extra_person_per_time_unit: true,
      category_prices: [{ category_id: CHILD, amount_minor: 3000 }],
      length_discounts: [{ min_length: 7, percent: 10 }],
    }),
    price({
      id: OWN,
      service_id: null,
      resource_id: UNIT,
      basis: "per_time_unit",
      amount_minor: 30000,
      vat_code: "8",
    }),
  ],
  amounts: "gross",
  categories: [child],
  extras: [
    extra({}),
    extra({
      id: "77777777-7777-4777-8777-777777777772",
      name: "Kaucja za sprzęt",
      kind: "security_deposit",
      amount_minor: 20000,
      vat_code: "np",
      mandatory: true,
      max_quantity: 1,
    }),
  ],
  ...given,
});

const quote = (given: Partial<BookingQuote> = {}): BookingQuote => ({
  currency: "PLN",
  amounts: "gross",
  lines: [
    {
      kind: "price",
      name: "Konsultacja",
      customer_name: "Konsultacja",
      quantity: 1,
      unit_amount_minor: 18000,
      net_minor: 14634,
      vat_minor: 3366,
      gross_minor: 18000,
      vat_code: "23",
      time_units: null,
      people: null,
      category_id: null,
      price_rule_id: WEEKEND,
      percent: null,
      extra_id: null,
    },
  ],
  participants: [{ category_id: null, count: 1 }],
  extras: [],
  security_deposit_minor: 20000,
  payment_policy: "on_site",
  net_minor: 14634,
  vat_minor: 3366,
  gross_minor: 18000,
  digest: "a".repeat(64),
  ...given,
});

function show(node: ReactNode, locale: "pl" | "en" = "pl") {
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

const changed = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
});

test("cennik oferty: ceny tak, jak je wpisano, dopłaty z kaucją i sposób płatności", async () => {
  show(
    <OfferPricesDialog
      book={book()}
      finalFocus={null}
      onChanged={changed}
      onOpenChange={() => undefined}
      onSetupChanged={changed}
      service={visit}
      setup={setup}
      zone="Europe/Warsaw"
    />,
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Cennik: Konsultacja",
  });
  const prices = within(dialog).getByRole("table", { name: "Ceny" });
  // Only this offer's prices: the stay's and the cottage's are not its own.
  expect(within(prices).getAllByRole("row")).toHaveLength(3);
  const base = within(prices).getByText("Cena podstawowa").closest("tr")!;
  expect(
    within(base).getByText(/150,00\szł za rezerwację/),
  ).toBeInTheDocument();
  const weekend = within(prices).getByText("Weekend").closest("tr")!;
  expect(
    within(weekend).getByText(/sob.*niedz.*10:00–14:00/),
  ).toBeInTheDocument();
  // The company enters gross amounts, and is told where that is set.
  expect(
    within(dialog).getByText("Kwoty w cenniku wpisujesz brutto (z VAT)."),
  ).toBeInTheDocument();
  expect(
    within(dialog).getByRole("link", {
      name: "Zmień w ustawieniach rezerwacji",
    }),
  ).toHaveAttribute("href", "/panel/settings/bookings");

  const extras = within(dialog).getByRole("table", {
    name: "Dopłaty i kaucja",
  });
  expect(
    within(extras).getByText(
      /30,00\szł za rezerwację · do wyboru, najwyżej 2 szt\. · VAT 23%/,
    ),
  ).toBeInTheDocument();
  const deposit = within(extras).getByText("Kaucja za sprzęt").closest("tr")!;
  expect(
    within(deposit).getByText(/200,00\szł · zwrotna, poza sumą, bez VAT/),
  ).toBeInTheDocument();
  expect((await axe.run(dialog, noContrast)).violations).toEqual([]);

  api.updateSetupService.mockResolvedValue({
    ...visit,
    payment_policy: "none",
  });
  fireEvent.change(within(dialog).getByLabelText("Jak płaci klient"), {
    target: { value: "none" },
  });
  await waitFor(() =>
    expect(api.updateSetupService).toHaveBeenCalledWith(
      VISIT,
      { payment_policy: "none", expected_version: 3 },
      expect.any(String),
    ),
  );
  expect(
    await within(dialog).findByText("Zapisano sposób płatności."),
  ).toBeInTheDocument();

  // A prepayment waits for its percent: choosing it saves nothing yet.
  api.updateSetupService.mockClear();
  fireEvent.change(within(dialog).getByLabelText("Jak płaci klient"), {
    target: { value: "deposit" },
  });
  expect(
    within(dialog).getByRole("link", {
      name: "Ustawienia › Płatności klientów",
    }),
  ).toHaveAttribute("href", "/panel/settings/customer-payments");
  expect(api.updateSetupService).not.toHaveBeenCalled();
  fireEvent.change(within(dialog).getByLabelText("Przedpłata (%)"), {
    target: { value: "0" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz warunki wpłaty" }),
  );
  expect(
    await within(dialog).findByText("Przedpłata to od 1 do 99 procent ceny."),
  ).toBeInTheDocument();
  expect(api.updateSetupService).not.toHaveBeenCalled();
  fireEvent.change(within(dialog).getByLabelText("Przedpłata (%)"), {
    target: { value: "40" },
  });
  fireEvent.change(within(dialog).getByLabelText("Dni na przelew"), {
    target: { value: "5" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz warunki wpłaty" }),
  );
  await waitFor(() =>
    expect(api.updateSetupService).toHaveBeenCalledWith(
      VISIT,
      {
        payment_policy: "deposit",
        transfer_due_days: 5,
        deposit_percent: 40,
        expected_version: 3,
      },
      expect.any(String),
    ),
  );

  // The whole by transfer saves at once; without the company's account the
  // server refuses and the panel says where to give one.
  api.updateSetupService.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Validation",
      status: 400,
      code: "validation_error",
      detail: "",
      correlation_id: null,
      errors: [
        {
          field: "payment_policy",
          code: "transfer_account_missing",
          message: "Najpierw podaj rachunek do przelewów.",
        },
      ],
    }),
  );
  fireEvent.change(within(dialog).getByLabelText("Jak płaci klient"), {
    target: { value: "transfer" },
  });
  expect(
    await within(dialog).findByText(
      "Najpierw podaj rachunek do przelewów: Ustawienia › Płatności klientów.",
    ),
  ).toBeInTheDocument();
});

test("„Jaka cena obowiązuje dnia…”: pyta serwer o sam cennik i mówi, która cena wygrała", async () => {
  api.getBookingQuote.mockResolvedValue(quote());
  show(
    <PriceList
      book={book()}
      description="Ceny tej oferty."
      onChanged={changed}
      service={visit}
      setup={setup}
      title="Ceny"
      zone="Europe/Warsaw"
    />,
  );
  const preview = screen.getByRole("region", {
    name: "Jaka cena obowiązuje dnia…",
  });
  fireEvent.change(within(preview).getByLabelText("Dzień"), {
    target: { value: "2027-07-03" },
  });
  fireEvent.change(within(preview).getByLabelText("Godzina"), {
    target: { value: "11:00" },
  });
  fireEvent.change(within(preview).getByLabelText("Osoby"), {
    target: { value: "2" },
  });
  fireEvent.change(within(preview).getByLabelText("Dziecko"), {
    target: { value: "1" },
  });
  fireEvent.click(within(preview).getByRole("button", { name: "Pokaż cenę" }));
  // The price list is asked, never added up here: 11:00 in Warsaw in July.
  await waitFor(() =>
    expect(api.getBookingQuote).toHaveBeenCalledWith({
      service_id: VISIT,
      starts_at: "2027-07-03T09:00:00.000Z",
      participants: [
        { category_id: null, count: 2 },
        { category_id: CHILD, count: 1 },
      ],
      price_only: true,
    }),
  );
  const answer = await within(preview).findByRole("region", {
    name: "Cena na ten termin",
  });
  // Which price wins is said in words, with what it applies to.
  expect(
    within(answer).getByText("Obowiązuje cena: Weekend · Oferta: Konsultacja"),
  ).toBeInTheDocument();
  expect(
    within(answer).getByText("Razem brutto").nextSibling,
  ).toHaveTextContent(/180,00\szł/);
  expect(
    within(answer).getByText(/Kaucja zwrotna: 200,00\szł \(poza sumą\)/),
  ).toBeInTheDocument();
  expect((await axe.run(preview, noContrast)).violations).toEqual([]);

  // Another question takes the old answer off the screen.
  fireEvent.change(within(preview).getByLabelText("Godzina"), {
    target: { value: "16:00" },
  });
  expect(
    within(preview).queryByRole("region", { name: "Cena na ten termin" }),
  ).toBeNull();

  // What the price list cannot price, in the server's own words.
  api.getBookingQuote.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Bad request",
      status: 400,
      code: "validation_error",
      detail: "Nieprawidłowe dane.",
      errors: [
        {
          field: "starts_at",
          code: "price_missing",
          message: "Cennik nie ma ceny na ten termin.",
        },
      ],
      correlation_id: null,
    }),
  );
  fireEvent.click(within(preview).getByRole("button", { name: "Pokaż cenę" }));
  expect(
    await within(preview).findByText("Cennik nie ma ceny na ten termin."),
  ).toBeInTheDocument();
});

test("the stays' price list asks about nights on a unit, and reads in English", async () => {
  api.getBookingQuote.mockResolvedValue(
    quote({ lines: [], security_deposit_minor: 0 }),
  );
  const { container } = show(
    <PriceList
      book={book({ amounts: "net" })}
      description="Prices of stays."
      onChanged={changed}
      setup={setup}
      title="Prices of stays"
      zone="Europe/Warsaw"
    />,
    "en",
  );
  const prices = screen.getByRole("table", { name: "Prices of stays" });
  // Every price that acts on a stay: the offer's season and the cottage's own.
  expect(within(prices).getAllByRole("row")).toHaveLength(3);
  const summer = within(prices).getByText("Lato").closest("tr")!;
  expect(
    within(summer).getByText(/PLN\s500\.00 per night/),
  ).toBeInTheDocument();
  expect(
    within(summer).getByText(
      /4 people included, each further one PLN\s60\.00 per night · Dziecko: PLN\s30\.00 · from 7 nights −10% · VAT 8%/,
    ),
  ).toBeInTheDocument();
  expect(within(prices).getByText("Unit: Domek 1")).toBeInTheDocument();
  expect(
    screen.getByText(/You enter the amounts in the price list net/),
  ).toBeInTheDocument();
  expect((await axe.run(container, noContrast)).violations).toEqual([]);

  const preview = screen.getByRole("region", {
    name: "Which price applies on…",
  });
  fireEvent.change(within(preview).getByLabelText("Arrival"), {
    target: { value: "2027-07-10" },
  });
  fireEvent.change(within(preview).getByLabelText("Number of nights"), {
    target: { value: "3" },
  });
  fireEvent.click(
    within(preview).getByRole("button", { name: "Show the price" }),
  );
  await waitFor(() =>
    expect(api.getBookingQuote).toHaveBeenCalledWith({
      service_id: STAY,
      start_date: "2027-07-10",
      end_date: "2027-07-13",
      participants: [{ category_id: null, count: 1 }],
      price_only: true,
    }),
  );
  expect(
    await within(preview).findByText(
      /This offer has no price in the price list/,
    ),
  ).toBeInTheDocument();
});

test("„za osobę za noc” jest własnym wyborem: zero za jednostkę, każda osoba za każdą noc", async () => {
  api.createBookingPrice.mockResolvedValue(
    price({ id: "new", service_id: STAY, basis: "per_time_unit" }),
  );
  show(
    <PriceList
      book={book({ amounts: "net" })}
      description="Ceny pobytów."
      onChanged={changed}
      setup={setup}
      title="Ceny pobytów"
      zone="Europe/Warsaw"
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Dodaj cenę" }));
  const dialog = await screen.findByRole("dialog", { name: "Dodaj cenę" });
  // A stay is counted per night first; a visit has no such choice.
  const basis = within(dialog).getByLabelText("Liczona");
  expect(
    within(basis)
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual([
    "za noc",
    "za osobę za noc",
    "za rezerwację",
    "za osobę",
    "za grupę",
  ]);
  expect(
    within(dialog).getByLabelText("Ile osób jest w cenie"),
  ).toBeInTheDocument();
  fireEvent.change(basis, { target: { value: "per_person_per_time_unit" } });
  // Nobody is "in the price" under it, and the company enters net amounts.
  expect(within(dialog).queryByLabelText("Ile osób jest w cenie")).toBeNull();
  fireEvent.change(within(dialog).getByLabelText("Kwota netto"), {
    target: { value: "80" },
  });
  fireEvent.change(within(dialog).getByLabelText("Stawka VAT"), {
    target: { value: "8" },
  });
  fireEvent.change(within(dialog).getByLabelText("Dziecko"), {
    target: { value: "40,50" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Dodaj próg rabatu" }),
  );
  fireEvent.change(within(dialog).getByLabelText("Od ilu nocy"), {
    target: { value: "7" },
  });
  fireEvent.change(within(dialog).getByLabelText("Rabat w %"), {
    target: { value: "10" },
  });
  expect((await axe.run(dialog, noContrast)).violations).toEqual([]);
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  await waitFor(() => expect(api.createBookingPrice).toHaveBeenCalled());
  expect(api.createBookingPrice.mock.calls[0][0]).toEqual({
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
    amount_minor: 0,
    vat_code: "8",
    included_people: 0,
    extra_person_amount_minor: 8000,
    extra_person_per_time_unit: true,
    category_prices: [{ category_id: CHILD, amount_minor: 4050 }],
    length_discounts: [{ min_length: 7, percent: 10 }],
    active: true,
  });
  await waitFor(() => expect(changed).toHaveBeenCalled());
});

test("cena z osobami w cenie: dopłata za kolejną jest wymagana, a odmowę serwera widać jego słowami", async () => {
  api.updateBookingPrice.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Bad request",
      status: 400,
      code: "validation_error",
      detail: "Nieprawidłowe dane.",
      errors: [
        {
          field: "length_discounts",
          code: "discount_must_grow",
          message: "Dłuższy pobyt musi mieć większy rabat niż krótszy.",
        },
      ],
      correlation_id: null,
    }),
  );
  show(
    <PriceList
      book={book()}
      description="Ceny pobytów."
      onChanged={changed}
      setup={setup}
      title="Ceny pobytów"
      zone="Europe/Warsaw"
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Edytuj: Lato" }));
  const dialog = await screen.findByRole("dialog", { name: "Edytuj cenę" });
  // The price as it was entered, in the company's way of writing amounts.
  expect(within(dialog).getByLabelText("Kwota brutto")).toHaveValue("500,00");
  expect(within(dialog).getByLabelText("Ile osób jest w cenie")).toHaveValue(4);
  expect(within(dialog).getByLabelText("Od")).toHaveValue("2027-07-01");
  const further = within(dialog).getByLabelText(
    "Dopłata za każdą kolejną osobę (brutto)",
  );
  fireEvent.change(further, { target: { value: "" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  expect(
    await within(dialog).findByText(
      "Podaj dopłatę za osobę ponad te w cenie (może być 0).",
    ),
  ).toBeInTheDocument();
  expect(api.updateBookingPrice).not.toHaveBeenCalled();

  fireEvent.change(further, { target: { value: "0" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  expect(
    await within(dialog).findByText(
      "Dłuższy pobyt musi mieć większy rabat niż krótszy.",
    ),
  ).toBeInTheDocument();
  expect(api.updateBookingPrice.mock.calls[0][1]).toMatchObject({
    basis: "per_time_unit",
    amount_minor: 50000,
    included_people: 4,
    extra_person_amount_minor: 0,
    extra_person_per_time_unit: true,
    starts_on: "2027-07-01",
    ends_on: "2027-08-31",
    expected_version: 1,
  });
});

test("kaucja to jedna kwota bez podstawy i VAT; kategorię dodaje się obok cennika", async () => {
  api.createBookingExtra.mockResolvedValue(
    extra({ name: "Kaucja", kind: "security_deposit" }),
  );
  api.createParticipantCategory.mockResolvedValue({ ...child, name: "Pies" });
  show(
    <>
      <ExtrasList
        amounts="gross"
        extras={[]}
        onChanged={changed}
        services={[stay]}
      />
      <PriceList
        book={book({ categories: [] })}
        description="Ceny pobytów."
        onChanged={changed}
        setup={setup}
        title="Ceny pobytów"
        zone="Europe/Warsaw"
      />
    </>,
  );
  expect(
    screen.getByText("Ta oferta nie ma dopłat ani kaucji."),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Dodaj dopłatę albo kaucję" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Dodaj dopłatę albo kaucję",
  });
  // A stay's extra may be per night and per person and night (a local tax).
  expect(
    within(within(dialog).getByLabelText("Liczona"))
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual(["za rezerwację", "za osobę", "za noc", "za osobę za noc"]);
  fireEvent.change(within(dialog).getByLabelText("Rodzaj"), {
    target: { value: "security_deposit" },
  });
  expect(within(dialog).queryByLabelText("Liczona")).toBeNull();
  expect(within(dialog).queryByLabelText("Stawka VAT")).toBeNull();
  fireEvent.change(within(dialog).getByLabelText("Nazwa"), {
    target: { value: "Kaucja" },
  });
  fireEvent.change(within(dialog).getByLabelText("Kwota kaucji"), {
    target: { value: "500" },
  });
  expect((await axe.run(dialog, noContrast)).violations).toEqual([]);
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(api.createBookingExtra).toHaveBeenCalledWith(
      {
        name: "Kaucja",
        kind: "security_deposit",
        amount_minor: 50000,
        active: true,
        service_id: STAY,
      },
      expect.any(String),
    ),
  );

  fireEvent.click(
    screen.getByRole("button", { name: "Kategorie uczestników" }),
  );
  const categories = await screen.findByRole("dialog", {
    name: "Kategorie uczestników",
  });
  fireEvent.change(within(categories).getByLabelText("Nazwa kategorii"), {
    target: { value: "Pies" },
  });
  fireEvent.click(
    within(categories).getByLabelText(/Zajmuje miejsce w jednostce/),
  );
  expect((await axe.run(categories, noContrast)).violations).toEqual([]);
  fireEvent.click(
    within(categories).getByRole("button", { name: "Dodaj kategorię" }),
  );
  await waitFor(() =>
    expect(api.createParticipantCategory).toHaveBeenCalledWith(
      { name: "Pies", counts_towards_capacity: false },
      expect.any(String),
    ),
  );
  expect(
    await within(categories).findByText("Dodano kategorię: Pies."),
  ).toBeInTheDocument();
});

test("a price that changed says so with the new amounts, and nothing is crossed out", async () => {
  const { container } = show(
    <PanelQuote
      changed
      quote={quote({
        amounts: "net",
        lines: [
          {
            ...quote().lines[0],
            quantity: 3,
            unit_amount_minor: 30000,
            gross_minor: 97200,
          },
          {
            ...quote().lines[0],
            kind: "discount",
            name: "Rabat za długość pobytu (10%)",
            unit_amount_minor: -9000,
            gross_minor: -9720,
            percent: 10,
          },
        ],
        net_minor: 81000,
        vat_minor: 6480,
        gross_minor: 87480,
      })}
    />,
    "en",
  );
  expect(screen.getByRole("alert")).toHaveTextContent("The price has changed.");
  // The amount is said the way it was entered; the line's total is gross.
  expect(
    screen.getByText(/Konsultacja × 3 at PLN\s300\.00 net/),
  ).toBeInTheDocument();
  expect(screen.getByText("Total, gross").nextSibling).toHaveTextContent(
    /PLN\s874\.80/,
  );
  expect(
    screen.getByText(/Refundable deposit: PLN\s200\.00 \(outside the total\)/),
  ).toBeInTheDocument();
  expect(screen.getByText("Payment on site.")).toBeInTheDocument();
  // A discount is a line of the price, never an old price struck through.
  expect(container.querySelector("s, del, strike, .line-through")).toBeNull();
  expect((await axe.run(container, noContrast)).violations).toEqual([]);
});

test("an amount is read as a person types it", () => {
  expect(parseAmount("150")).toBe(15000);
  expect(parseAmount("149,9")).toBe(14990);
  expect(parseAmount("1 200.50")).toBe(120050);
  expect(parseAmount("")).toBeNull();
  expect(parseAmount("12,345")).toBeNull();
  expect(parseAmount("-5")).toBeNull();
});
