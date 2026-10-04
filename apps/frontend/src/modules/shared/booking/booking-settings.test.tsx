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

import { ApiProblemError } from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import messages from "../../../../messages/pl.json";
import { BookingSettings } from "./booking-settings";

const api = vi.hoisted(() => ({
  copyBookingClosuresToNextYear: vi.fn(),
  copyBookingRulesToNextYear: vi.fn(),
  createBookingClosure: vi.fn(),
  createBookingRule: vi.fn(),
  createSetupGroup: vi.fn(),
  createSetupLocation: vi.fn(),
  createSetupResource: vi.fn(),
  createSetupService: vi.fn(),
  deleteBookingClosure: vi.fn(),
  getBookingSetup: vi.fn(),
  listBookingClosures: vi.fn(),
  listBookingExtras: vi.fn(),
  listBookingPrices: vi.fn(),
  listBookingRules: vi.fn(),
  listParticipantCategories: vi.fn(),
  listInventoryBalances: vi.fn(),
  listInventoryItems: vi.fn(),
  getMediaAssetPreview: vi.fn(),
  readCatalogDictionary: vi.fn(),
  updateSetupGroup: vi.fn(),
  updateSetupLocation: vi.fn(),
  updateSetupResource: vi.fn(),
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

// A type with one ready-made service, as a product's type brings them.
vi.mock("#lib/organization-types", async (original) => {
  const real = await original<typeof import("#lib/organization-types")>();
  return {
    ...real,
    organizationType: (key?: string | null) =>
      key === "farm-care"
        ? {
            ...real.organizationType(),
            serviceTemplates: [
              {
                key: "herd",
                label: { pl: "Korekcja stada", en: "Herd trimming" },
                durationMinutes: 300,
                appointmentKind: "farm_visit",
              },
            ],
          }
        : real.organizationType(key),
  };
});

const MARCIN = "22222222-2222-4222-8222-222222222222";
const PIOTR = "22222222-2222-4222-8222-333333333333";
const BASE = "11111111-1111-4111-8111-111111111111";
const BRANCH = "11111111-1111-4111-8111-222222222222";
const ROOM = "44444444-4444-4444-8444-444444444444";
const HERD = "33333333-3333-4333-8333-333333333333";
const GROUP = "55555555-5555-4555-8555-555555555555";
const OLD = "33333333-3333-4333-8333-444444444444";

const service = (over: Record<string, unknown>) => ({
  id: HERD,
  name: "Korekcja stada 60–150 krów",
  appointment_kind: "",
  time_model: "slot",
  range_unit: "",
  range_start_local: null,
  range_end_local: null,
  group_ids: [],
  duration_minutes: 90,
  buffer_before_minutes: 0,
  buffer_after_minutes: 30,
  minimum_notice_minutes: 60,
  staff_count: 2,
  public_staff_choice: "team",
  online: true,
  active: true,
  draft: false,
  preset_id: null,
  preset_version: null,
  staff_ids: [MARCIN, PIOTR],
  location_ids: [BASE],
  resource_ids: [],
  materials: [],
  takes_materials: true,
  version: 3,
  future_bookings: 0,
  ...over,
});

const SETUP = {
  services: [
    service({}),
    service({
      id: OLD,
      name: "Wizyta interwencyjna",
      duration_minutes: 60,
      staff_count: 1,
      public_staff_choice: "none",
      online: false,
      active: false,
      staff_ids: [],
    }),
  ],
  locations: [
    {
      id: BASE,
      name: "Baza Radziejów",
      address: "ul. Polna 1",
      active: true,
      version: 1,
    },
    { id: BRANCH, name: "Filia", address: "", active: false, version: 2 },
  ],
  resources: [
    {
      id: ROOM,
      name: "Poskrom",
      active: true,
      group_id: null,
      location_id: BASE,
      capacity: null,
      description: "",
      public: false,
      public_slug: "",
      amenities: [] as string[],
      city_slug: "",
      latitude: null as number | null,
      longitude: null as number | null,
      photo_ids: [] as string[],
      version: 1,
    },
  ],
  unit_options: {
    amenities: [
      { key: "wifi", label: { pl: "Wi-Fi", en: "Wi-Fi", de: "WLAN" } },
      { key: "sauna", label: { pl: "Sauna", en: "Sauna", de: "Sauna" } },
      { key: "fireplace", label: { pl: "Kominek", en: "Fireplace" } },
    ],
    max_photos: 2,
  },
  groups: [
    {
      id: GROUP,
      name: "Poskrom mobilny",
      description: "",
      active: true,
      version: 2,
    },
  ],
  staff: [
    { id: MARCIN, name: "Marcin Kowalski", hours_version: 1 },
    { id: PIOTR, name: "Piotr Wiśniewski", hours_version: 1 },
  ],
  appointment_kinds: [] as { key: string; label: string }[],
};

const problem = (status: number, code: string, detail: string) =>
  new ApiProblemError({
    type: "about:blank",
    title: code,
    status,
    code,
    detail,
    correlation_id: null,
  });

const noContrast = { rules: { "color-contrast": { enabled: false } } };

function renderSettings({
  canManageBilling = true,
  canUseInventory = false,
  locale = "pl",
  organizationType,
}: {
  canManageBilling?: boolean;
  canUseInventory?: boolean;
  locale?: "pl" | "en";
  organizationType?: string;
} = {}) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? messages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <BookingSettings
        canManageBilling={canManageBilling}
        canUseInventory={canUseInventory}
        organizationType={organizationType}
      />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getBookingSetup.mockResolvedValue(SETUP);
  api.listBookingClosures.mockResolvedValue([]);
  api.listBookingRules.mockResolvedValue([]);
  // No price list yet: every offer says so.
  api.listBookingPrices.mockResolvedValue({ items: [], amounts: "gross" });
  api.listParticipantCategories.mockResolvedValue([]);
  api.listBookingExtras.mockResolvedValue([]);
  api.createSetupService.mockImplementation(async (input) =>
    service({ ...input, id: "new" }),
  );
  api.updateSetupService.mockImplementation(async (id, input) =>
    service({ id, ...input }),
  );
  api.createSetupLocation.mockImplementation(async (input) => ({
    id: "place",
    active: true,
    address: "",
    ...input,
  }));
  api.updateSetupLocation.mockImplementation(async (id, input) => ({
    id,
    ...input,
  }));
  api.listInventoryItems.mockResolvedValue([]);
  api.listInventoryBalances.mockResolvedValue([]);
  // A unit's pictures are previews the panel asks for; none comes in a test.
  api.getMediaAssetPreview.mockReturnValue(new Promise(() => undefined));
  api.readCatalogDictionary.mockResolvedValue({ cities: [], categories: [] });
});

test("usługi, miejsca i zasoby w listach, z tym, co trzeba poprawić", async () => {
  const { container } = renderSettings();
  const services = await screen.findByRole("table", { name: "Usługi firmy" });
  const herd = within(services)
    .getByText("Korekcja stada 60–150 krów")
    .closest("tr")!;
  expect(within(herd).getByText("1 h 30 min")).toBeInTheDocument();
  // Of the company's two people, both can do it (UX-059).
  expect(within(herd).getByText("2 z 2 osób")).toBeInTheDocument();
  expect(
    within(herd).getByText("Tak, klient wybiera zespół"),
  ).toBeInTheDocument();
  // No module of the company provides a kind of visit: no „Rodzaj” column.
  expect(
    within(services).queryByRole("columnheader", { name: "Rodzaj" }),
  ).toBeNull();
  const old = within(services).getByText("Wizyta interwencyjna").closest("tr")!;
  expect(within(old).getByText("Wyłączona")).toBeInTheDocument();
  // Hidden from the site's form: the list does not say customers book it.
  expect(
    within(old).getByText("Nie — rezerwacje wpisuje zespół"),
  ).toBeInTheDocument();
  // Nobody does it: said where it is set, not discovered in the calendar.
  expect(within(old).getByText("Nikt")).toBeInTheDocument();
  const places = screen.getByRole("table", { name: "Miejsca firmy" });
  expect(within(places).getByText("ul. Polna 1")).toBeInTheDocument();
  expect(within(places).getByText("Wyłączone")).toBeInTheDocument();
  expect(
    within(screen.getByRole("table", { name: "Zasoby firmy" })).getByText(
      "Poskrom",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Otwórz listę pracowników" }),
  ).toHaveAttribute("href", "/panel/team");
  expect((await axe.run(container, noContrast)).violations).toEqual([]);
});

test("usługa pokazuje swoją cenę, a „Cennik” otwiera jej ceny, dopłaty i podgląd", async () => {
  api.listBookingPrices.mockResolvedValue({
    items: [
      {
        id: "price",
        name: "",
        service_id: HERD,
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
      },
    ],
    amounts: "gross",
  });
  renderSettings();
  const services = await screen.findByRole("table", { name: "Usługi firmy" });
  const herd = within(services)
    .getByText("Korekcja stada 60–150 krów")
    .closest("tr")!;
  expect(
    await within(herd).findByText(/150,00\szł za rezerwację/),
  ).toBeInTheDocument();
  const old = within(services).getByText("Wizyta interwencyjna").closest("tr")!;
  expect(within(old).getByText("Bez ceny")).toBeInTheDocument();

  fireEvent.click(within(herd).getByRole("button", { name: "Cennik" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Cennik: Korekcja stada 60–150 krów",
  });
  expect(
    within(within(dialog).getByRole("table", { name: "Ceny" })).getByText(
      "Cena podstawowa",
    ),
  ).toBeInTheDocument();
  expect(
    within(dialog).getByRole("region", { name: "Jaka cena obowiązuje dnia…" }),
  ).toBeInTheDocument();
  expect(
    within(dialog).getByRole("table", { name: "Dopłaty i kaucja" }),
  ).toBeInTheDocument();
  expect((await axe.run(dialog, noContrast)).violations).toEqual([]);
});

test("cennik oferty nad cenami pobytów: każda etykieta trafia do swojego pola", async () => {
  // A company that books by dates has the stays' prices on the page, with
  // their own preview — and an offer's „Cennik” opens a second one over it.
  api.getBookingSetup.mockResolvedValue({
    ...SETUP,
    services: [
      ...SETUP.services,
      service({
        id: "stay",
        name: "Pobyt w domku",
        time_model: "range",
        range_unit: "night",
        duration_minutes: null,
        staff_count: 0,
        staff_ids: [],
        group_ids: [GROUP],
      }),
    ],
  });
  renderSettings();
  const stays = await screen.findByRole("table", { name: "Ceny pobytów" });
  expect(stays).toBeInTheDocument();
  const services = screen.getByRole("table", { name: "Usługi firmy" });
  const herd = within(services)
    .getByText("Korekcja stada 60–150 krów")
    .closest("tr")!;
  fireEvent.click(within(herd).getByRole("button", { name: "Cennik" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Cennik: Korekcja stada 60–150 krów",
  });
  expect(
    screen.getAllByRole("region", {
      name: "Jaka cena obowiązuje dnia…",
      hidden: true,
    }),
  ).toHaveLength(2);
  const ids = [...document.querySelectorAll("[id]")].map((node) => node.id);
  expect(ids.filter((id, at) => ids.indexOf(id) !== at)).toEqual([]);
  // The dialog's „Dzień” is the dialog's field, not the page's under it.
  expect(dialog).toContainElement(within(dialog).getByLabelText("Dzień"));
});

test("edycja usługi zapisuje ile osób, kto, gdzie, czym i co wybiera klient", async () => {
  renderSettings();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Edytuj: Korekcja stada 60–150 krów",
    }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Edytuj usługę: Korekcja stada 60–150 krów",
  });
  // Only active places are offered; the one switched off is not a choice.
  expect(within(dialog).queryByLabelText("Filia")).toBeNull();
  fireEvent.change(within(dialog).getByLabelText("Ile osób potrzeba"), {
    target: { value: "3" },
  });
  expect(
    await within(dialog).findByText(/Usługa wymaga 3 osób, a zaznaczono mniej/),
  ).toBeInTheDocument();
  fireEvent.change(within(dialog).getByLabelText("Ile osób potrzeba"), {
    target: { value: "2" },
  });
  fireEvent.click(within(dialog).getByLabelText("Poskrom"));
  // A person is a customer's choice only for a one-person service.
  fireEvent.change(within(dialog).getByLabelText("Klient może wybrać"), {
    target: { value: "person" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz usługę" }),
  );
  expect(
    await within(dialog).findByText(
      "Osobę klient wybiera tylko przy usłudze dla jednej osoby.",
    ),
  ).toBeInTheDocument();
  expect(api.updateSetupService).not.toHaveBeenCalled();
  fireEvent.change(within(dialog).getByLabelText("Klient może wybrać"), {
    target: { value: "team" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz usługę" }),
  );
  expect(
    await screen.findByText("Zapisano: Korekcja stada 60–150 krów."),
  ).toBeInTheDocument();
  expect(api.updateSetupService).toHaveBeenCalledWith(
    HERD,
    {
      name: "Korekcja stada 60–150 krów",
      time_model: "slot",
      duration_minutes: 90,
      buffer_before_minutes: 0,
      buffer_after_minutes: 30,
      minimum_notice_minutes: 60,
      staff_count: 2,
      public_staff_choice: "team",
      // The start grid and the site's form (B6, B2): as the service had them.
      slot_step_minutes: 5,
      online: true,
      staff_ids: [MARCIN, PIOTR],
      location_ids: [BASE],
      resource_ids: [ROOM],
      // The version the dialog was opened on (ADR-072 §11).
      expected_version: 3,
    },
    expect.any(String),
  );
  expect(api.getBookingSetup).toHaveBeenCalledTimes(2);
});

test("usługa potwierdzana na prośbę zapisuje, kto potwierdza i ile ma czasu (ADR-072 §9)", async () => {
  renderSettings();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Edytuj: Korekcja stada 60–150 krów",
    }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Edytuj usługę: Korekcja stada 60–150 krów",
  });
  // The time to answer is asked for only where the company answers.
  expect(
    within(dialog).queryByLabelText("Czas na odpowiedź (godz.)"),
  ).toBeNull();
  fireEvent.change(within(dialog).getByLabelText("Potwierdzenie rezerwacji"), {
    target: { value: "on_request" },
  });
  const hours = await within(dialog).findByLabelText(
    "Czas na odpowiedź (godz.)",
  );
  expect(hours).toHaveValue(24);
  fireEvent.change(hours, { target: { value: "0" } });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz usługę" }),
  );
  expect(
    await within(dialog).findByText("Czas na odpowiedź to od 1 do 168 godzin."),
  ).toBeInTheDocument();
  expect(api.updateSetupService).not.toHaveBeenCalled();
  fireEvent.change(hours, { target: { value: "12" } });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz usługę" }),
  );
  await waitFor(() =>
    expect(api.updateSetupService).toHaveBeenCalledWith(
      HERD,
      expect.objectContaining({
        confirmation: "on_request",
        response_hours: 12,
        expected_version: 3,
      }),
      expect.any(String),
    ),
  );
});

test("gotowa usługa typu firmy otwiera formularz z nazwą i czasem", async () => {
  renderSettings({ organizationType: "farm-care" });
  fireEvent.click(
    await screen.findByRole("button", { name: "Korekcja stada" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Nowa usługa" });
  expect(within(dialog).getByLabelText("Nazwa")).toHaveValue("Korekcja stada");
  expect(within(dialog).getByLabelText("Czas trwania (min)")).toHaveValue(300);
  fireEvent.click(within(dialog).getByLabelText("Marcin Kowalski"));
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz usługę" }),
  );
  await waitFor(() => expect(api.createSetupService).toHaveBeenCalled());
  // The one active place goes with it; the kind of visit comes from the type.
  expect(api.createSetupService.mock.calls[0][0]).toMatchObject({
    name: "Korekcja stada",
    duration_minutes: 300,
    appointment_kind: "farm_visit",
    staff_ids: [MARCIN],
    location_ids: [BASE],
  });
  expect(
    await screen.findByText("Dodano: Korekcja stada."),
  ).toBeInTheDocument();
});

test("wyłączenie usługi i nowe miejsce z adresem", async () => {
  renderSettings();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Więcej: Korekcja stada 60–150 krów",
    }),
  );
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "Wyłącz usługę" }),
  );
  await waitFor(() =>
    expect(api.updateSetupService).toHaveBeenCalledWith(
      HERD,
      { active: false, expected_version: 3 },
      expect.any(String),
    ),
  );
  expect(
    await screen.findByText("Wyłączono: Korekcja stada 60–150 krów."),
  ).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Dodaj miejsce" }));
  const dialog = await screen.findByRole("dialog", { name: "Nowe miejsce" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  expect(await within(dialog).findByText("Podaj nazwę.")).toBeInTheDocument();
  fireEvent.change(within(dialog).getByLabelText("Nazwa"), {
    target: { value: "Gabinet Toruń" },
  });
  fireEvent.change(within(dialog).getByLabelText("Adres"), {
    target: { value: "ul. Długa 2" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(api.createSetupLocation).toHaveBeenCalledWith(
      { name: "Gabinet Toruń", address: "ul. Długa 2", online: true },
      expect.any(String),
    ),
  );
});

test("wyłączenie usługi z przyszłymi rezerwacjami pyta, ile zostaje, i nie odwołuje ich (W1)", async () => {
  api.getBookingSetup.mockResolvedValue({
    ...SETUP,
    services: [service({ future_bookings: 3, appointment_kind: "farm_visit" })],
    appointment_kinds: [{ key: "farm_visit", label: "Wizyta w gospodarstwie" }],
  });
  renderSettings();
  const services = await screen.findByRole("table", { name: "Usługi firmy" });
  expect(
    within(services).getByRole("columnheader", { name: "Rodzaj" }),
  ).toBeInTheDocument();
  expect(
    within(services).getByText("Wizyta w gospodarstwie"),
  ).toBeInTheDocument();

  fireEvent.click(
    screen.getByRole("button", { name: "Więcej: Korekcja stada 60–150 krów" }),
  );
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "Wyłącz usługę" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Wyłączyć usługę Korekcja stada 60–150 krów?",
  });
  expect(
    within(dialog).getByText(/Zostają 3 przyszłe rezerwacje tej usługi/),
  ).toBeInTheDocument();
  expect(api.updateSetupService).not.toHaveBeenCalled();
  expect(
    within(dialog).getByRole("link", { name: "Pokaż w kalendarzu" }),
  ).toHaveAttribute(
    "href",
    "/panel/calendar?view=list&service=Korekcja%20stada%2060%E2%80%93150%20kr%C3%B3w",
  );
  expect((await axe.run(dialog, noContrast)).violations).toEqual([]);
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Wyłącz mimo to" }),
  );
  await waitFor(() =>
    expect(api.updateSetupService).toHaveBeenCalledWith(
      HERD,
      { active: false, expected_version: 3 },
      expect.any(String),
    ),
  );
});

test("a refusal from the server is shown in the dialog (EN)", async () => {
  api.updateSetupService.mockRejectedValue(
    problem(400, "validation_error", "Nie ma takiej pozycji."),
  );
  renderSettings({ locale: "en" });
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Edit: Korekcja stada 60–150 krów",
    }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Edit service: Korekcja stada 60–150 krów",
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Save service" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    "Nie ma takiej pozycji.",
  );
});

test("grupa jednostek i jednostka w grupie z pojemnością", async () => {
  api.createSetupGroup.mockImplementation(async (input) => ({
    id: "g-new",
    description: "",
    active: true,
    version: 1,
    ...input,
  }));
  api.updateSetupResource.mockImplementation(async (id, input) => ({
    ...SETUP.resources[0],
    ...input,
    id,
  }));
  renderSettings();
  fireEvent.click(await screen.findByRole("button", { name: "Dodaj grupę" }));
  const dialog = await screen.findByRole("dialog", { name: "Nowa grupa" });
  fireEvent.change(within(dialog).getByLabelText("Nazwa"), {
    target: { value: "Domek 6-os." },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(api.createSetupGroup).toHaveBeenCalledWith(
      { name: "Domek 6-os.", description: "" },
      expect.any(String),
    ),
  );
  expect(await screen.findByText("Dodano: Domek 6-os..")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Edytuj: Poskrom" }));
  const unit = await screen.findByRole("dialog", {
    name: "Edytuj zasób: Poskrom",
  });
  fireEvent.change(within(unit).getByLabelText("Grupa"), {
    target: { value: GROUP },
  });
  fireEvent.change(within(unit).getByLabelText("Ile osób mieści"), {
    target: { value: "0" },
  });
  fireEvent.click(within(unit).getByRole("button", { name: "Zapisz" }));
  expect(await within(unit).findByRole("alert")).toHaveTextContent(
    "Pojemność to od 1 do 1000 osób.",
  );
  fireEvent.change(within(unit).getByLabelText("Ile osób mieści"), {
    target: { value: "6" },
  });
  fireEvent.click(within(unit).getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(api.updateSetupResource).toHaveBeenCalledWith(
      ROOM,
      {
        name: "Poskrom",
        group_id: GROUP,
        location_id: BASE,
        capacity: 6,
        description: "",
        expected_version: 1,
      },
      expect.any(String),
    ),
  );
});

test("jednostka firmy z pobytami: co widzi gość — adres, miejscowość, współrzędne, wyposażenie i zdjęcia", async () => {
  // A company with visits only is asked nothing about content.
  const visits = renderSettings();
  fireEvent.click(
    await screen.findByRole("button", { name: "Edytuj: Poskrom" }),
  );
  const plain = await screen.findByRole("dialog", {
    name: "Edytuj zasób: Poskrom",
  });
  expect(within(plain).queryByLabelText("Pokaż jednostkę gościom")).toBeNull();
  visits.unmount();

  const stay = service({
    id: "stay",
    name: "Pobyt w domku",
    time_model: "range",
    range_unit: "night",
    duration_minutes: null,
    staff_count: 0,
    staff_ids: [],
    group_ids: [GROUP],
  });
  const PHOTO = "66666666-6666-4666-8666-666666666666";
  const COVER = "77777777-7777-4777-8777-777777777777";
  api.getBookingSetup.mockResolvedValue({
    ...SETUP,
    services: [stay],
    resources: [
      {
        ...SETUP.resources[0],
        name: "Domek 1",
        public: true,
        public_slug: "domek-1",
        amenities: ["sauna"],
        photo_ids: [PHOTO, COVER],
      },
    ],
  });
  api.readCatalogDictionary.mockResolvedValue({
    cities: [
      { slug: "mragowo", name: "Mrągowo", voivodeship: "warmińsko-mazurskie" },
    ],
    categories: [],
  });
  api.updateSetupResource.mockImplementation(async (id, input) => ({
    ...SETUP.resources[0],
    ...input,
    id,
  }));
  renderSettings();
  // The list says which units guests are shown, and that the stay — shown
  // online — is booked on the site's form by its dates.
  expect(await screen.findByText("widoczna dla gości")).toBeInTheDocument();
  expect(screen.getByText("Tak, gość wybiera daty")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Edytuj: Domek 1" }));
  const unit = await screen.findByRole("dialog", {
    name: "Edytuj zasób: Domek 1",
  });
  expect(within(unit).getByLabelText("Pokaż jednostkę gościom")).toBeChecked();
  expect(within(unit).getByLabelText("Adres jednostki")).toHaveValue("domek-1");
  expect(within(unit).getByLabelText("Sauna")).toBeChecked();
  // Two pictures are the most this unit takes: nothing more to add.
  expect(within(unit).queryByText("Dodaj zdjęcie")).toBeNull();
  await within(unit).findByRole("option", { name: "Mrągowo" });
  fireEvent.change(within(unit).getByLabelText("Miejscowość"), {
    target: { value: "mragowo" },
  });
  fireEvent.click(within(unit).getByLabelText("Kominek"));
  fireEvent.click(
    within(unit).getByRole("button", { name: "Ustaw zdjęcie 2 jako okładkę" }),
  );
  // One coordinate without the other is said before anything is sent.
  fireEvent.change(within(unit).getByLabelText("Szerokość geograficzna"), {
    target: { value: "53,8645" },
  });
  fireEvent.click(within(unit).getByRole("button", { name: "Zapisz" }));
  expect(await within(unit).findByRole("alert")).toHaveTextContent(
    "Podaj obie współrzędne albo żadnej.",
  );
  expect(api.updateSetupResource).not.toHaveBeenCalled();
  fireEvent.change(within(unit).getByLabelText("Długość geograficzna"), {
    target: { value: "21.305" },
  });
  fireEvent.click(within(unit).getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(api.updateSetupResource).toHaveBeenCalledWith(
      ROOM,
      {
        name: "Domek 1",
        group_id: null,
        location_id: BASE,
        capacity: null,
        description: "",
        public: true,
        public_slug: "domek-1",
        city_slug: "mragowo",
        latitude: "53.864500",
        longitude: "21.305000",
        amenities: ["sauna", "fireplace"],
        photo_ids: [COVER, PHOTO],
        expected_version: 1,
      },
      expect.any(String),
    ),
  );
});

test("pobyt na noce: grupa jednostek, zameldowanie i wymeldowanie, bez osób", async () => {
  renderSettings();
  fireEvent.click(await screen.findByRole("button", { name: "Dodaj usługę" }));
  const dialog = await screen.findByRole("dialog", { name: "Nowa usługa" });
  fireEvent.change(within(dialog).getByLabelText("Nazwa"), {
    target: { value: "Pobyt w domku" },
  });
  fireEvent.change(within(dialog).getByLabelText("Jak się rezerwuje"), {
    target: { value: "range" },
  });
  expect(within(dialog).queryByLabelText("Czas trwania (min)")).toBeNull();
  expect(within(dialog).getByLabelText("Zameldowanie / odbiór")).toHaveValue(
    "16:00",
  );
  fireEvent.click(within(dialog).getByLabelText("Poskrom mobilny"));
  // The offer's own booking window: empty until the company sets one.
  const window = within(dialog).getByLabelText("Okno rezerwacji (dni)");
  expect(window).toHaveValue(null);
  fireEvent.change(window, { target: { value: "900" } });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz usługę" }),
  );
  expect(
    await within(dialog).findByText("Okno to od 1 do 731 dni albo puste pole."),
  ).toBeInTheDocument();
  expect(api.createSetupService).not.toHaveBeenCalled();
  fireEvent.change(window, { target: { value: "180" } });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz usługę" }),
  );
  await waitFor(() => expect(api.createSetupService).toHaveBeenCalled());
  const [body] = api.createSetupService.mock.calls[0];
  expect(body).toMatchObject({
    name: "Pobyt w domku",
    time_model: "range",
    range_unit: "night",
    range_start_local: "16:00",
    range_end_local: "11:00",
    booking_window_days: 180,
    group_ids: [GROUP],
    staff_count: 0,
    staff_ids: [],
  });
  expect(body).not.toHaveProperty("duration_minutes");
});

test("dni zamknięte: dodanie dla całej firmy i kopia na kolejny rok", async () => {
  const christmas = {
    id: "c-1",
    location_id: null,
    starts_on: "2027-12-24",
    ends_on: "2027-12-26",
    note: "Święta",
    version: 1,
  };
  api.createBookingClosure.mockResolvedValue(christmas);
  api.copyBookingClosuresToNextYear.mockResolvedValue(1);
  renderSettings();
  fireEvent.click(
    await screen.findByRole("button", { name: "Dodaj dni zamknięte" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Nowe dni zamknięte",
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    "Podaj pierwszy i ostatni dzień.",
  );
  fireEvent.change(within(dialog).getByLabelText("Od"), {
    target: { value: "2027-12-24" },
  });
  fireEvent.change(within(dialog).getByLabelText("Do (włącznie)"), {
    target: { value: "2027-12-26" },
  });
  fireEvent.change(within(dialog).getByLabelText("Notatka (tylko dla firmy)"), {
    target: { value: "Święta" },
  });
  api.listBookingClosures.mockResolvedValue([christmas]);
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(api.createBookingClosure).toHaveBeenCalledWith(
      {
        starts_on: "2027-12-24",
        ends_on: "2027-12-26",
        location_id: null,
        note: "Święta",
      },
      expect.any(String),
    ),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Skopiuj z 2027 na 2028" }),
  );
  await waitFor(() =>
    expect(api.copyBookingClosuresToNextYear).toHaveBeenCalledWith(
      2027,
      expect.any(String),
    ),
  );
  expect(
    await screen.findByText("Skopiowano 1 zamknięcie na 2028 — sprawdź daty."),
  ).toBeInTheDocument();
});

test("sezony: tylko przy pobytach; nowy sezon grupy z zasadami słowami i kopia na kolejny rok", async () => {
  // A company without an offer booked by dates has no seasons to set.
  const { unmount } = renderSettings();
  await screen.findByRole("table", { name: "Usługi firmy" });
  expect(screen.queryByRole("heading", { name: "Sezony i zasady" })).toBeNull();
  unmount();

  const stay = service({
    id: "stay",
    name: "Pobyt w domku",
    time_model: "range",
    range_unit: "night",
    duration_minutes: null,
    staff_count: 0,
    staff_ids: [],
    group_ids: [GROUP],
  });
  api.getBookingSetup.mockResolvedValue({ ...SETUP, services: [stay] });
  const summer = {
    id: "r-1",
    name: "Lato",
    service_id: null,
    group_id: GROUP,
    resource_id: null,
    starts_on: "2027-07-01",
    ends_on: "2027-08-31",
    min_length: 2,
    max_length: null,
    length_multiple: null,
    start_weekdays: [5],
    end_weekdays: [],
    notice_hours: null,
    window_days: null,
    closed: false,
    buffer_after_minutes: null,
    active: true,
    version: 1,
  };
  api.createBookingRule.mockResolvedValue(summer);
  api.copyBookingRulesToNextYear.mockResolvedValue(1);
  renderSettings();
  fireEvent.click(await screen.findByRole("button", { name: "Dodaj sezon" }));
  const dialog = await screen.findByRole("dialog", { name: "Nowy sezon" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    "Podaj pierwszy i ostatni dzień sezonu.",
  );
  fireEvent.change(within(dialog).getByLabelText("Nazwa (opcjonalnie)"), {
    target: { value: "Lato" },
  });
  fireEvent.change(within(dialog).getByLabelText("Dotyczy"), {
    target: { value: `group:${GROUP}` },
  });
  fireEvent.change(within(dialog).getByLabelText("Od"), {
    target: { value: "2027-07-01" },
  });
  fireEvent.change(within(dialog).getByLabelText("Do (włącznie)"), {
    target: { value: "2027-08-31" },
  });
  fireEvent.change(within(dialog).getByLabelText("Najkrótszy pobyt"), {
    target: { value: "2" },
  });
  const arrival = within(dialog).getByRole("group", { name: /Dni przyjazdu/ });
  fireEvent.click(within(arrival).getByLabelText("sob."));
  expect((await axe.run(dialog, noContrast)).violations).toEqual([]);
  api.listBookingRules.mockResolvedValue([summer]);
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(api.createBookingRule).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Lato",
        service_id: null,
        group_id: GROUP,
        resource_id: null,
        starts_on: "2027-07-01",
        ends_on: "2027-08-31",
        closed: false,
        min_length: 2,
        max_length: null,
        start_weekdays: [5],
        end_weekdays: [],
      }),
      expect.any(String),
    ),
  );
  const seasons = await screen.findByRole("table", {
    name: "Sezony i zasady pobytów",
  });
  const row = (await within(seasons).findByText("Lato")).closest("tr")!;
  expect(within(row).getByText("Grupa: Poskrom mobilny")).toBeInTheDocument();
  expect(
    within(row).getByText("od 2 nocy · przyjazd: sob."),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Skopiuj sezony 2027 na 2028" }),
  );
  await waitFor(() =>
    expect(api.copyBookingRulesToNextYear).toHaveBeenCalledWith(
      2027,
      expect.any(String),
    ),
  );
  expect(
    await screen.findByText("Skopiowano 1 sezon na rok 2028."),
  ).toBeInTheDocument();
});

test("zmiana, której ktoś w międzyczasie nie widział, mówi o tym zamiast nadpisać", async () => {
  api.updateSetupService.mockRejectedValue(
    problem(409, "booking_version_conflict", "Ktoś zmienił to w międzyczasie."),
  );
  renderSettings();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Edytuj: Korekcja stada 60–150 krów",
    }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Edytuj usługę: Korekcja stada 60–150 krów",
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz usługę" }),
  );
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    "Zamknij okno — lista pokaże aktualne dane",
  );
  fireEvent.click(within(dialog).getByRole("button", { name: "Anuluj" }));
  // Closing it reads the list again, with the other person's version.
  await waitFor(() => expect(api.getBookingSetup).toHaveBeenCalledTimes(2));
});

test("bez rezerwacji w planie: właściciel idzie do planów, reszta pyta właściciela", async () => {
  api.getBookingSetup.mockRejectedValue(
    problem(403, "entitlement_required", "Plan organizacji nie pozwala."),
  );
  const { container, unmount } = renderSettings();

  expect(
    await screen.findByRole("heading", {
      name: "Rezerwacje nie są w Twoim planie",
    }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Zobacz plany" })).toHaveAttribute(
    "href",
    "/panel/settings/billing",
  );
  expect((await axe.run(container, noContrast)).violations).toEqual([]);
  unmount();

  renderSettings({ canManageBilling: false });
  expect(
    await screen.findByText(/Poproś właściciela firmy o zmianę planu/),
  ).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Zobacz plany" })).toBeNull();
});

test("błąd wczytywania daje ponowienie", async () => {
  api.getBookingSetup
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce(SETUP);
  renderSettings();

  fireEvent.click(
    await screen.findByRole("button", { name: "Spróbuj ponownie" }),
  );

  expect(
    await screen.findByRole("table", { name: "Usługi firmy" }),
  ).toBeInTheDocument();
  expect(api.getBookingSetup).toHaveBeenCalledTimes(2);
});

test("produkty z magazynu tylko przy usłudze, której materiał nie idzie przez moduł", async () => {
  api.getBookingSetup.mockResolvedValue({
    ...SETUP,
    services: [
      // Like HoofCare's herd visit: material goes per cow, never from here.
      service({ takes_materials: false }),
      service({
        id: OLD,
        name: "Masaż",
        staff_count: 1,
        takes_materials: true,
      }),
    ],
  });
  renderSettings({ canUseInventory: true });
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Edytuj: Korekcja stada 60–150 krów",
    }),
  );
  let dialog = await screen.findByRole("dialog", {
    name: /Edytuj usługę: Korekcja stada/,
  });
  expect(within(dialog).queryByText("Produkty z magazynu")).toBeNull();
  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

  fireEvent.click(screen.getByRole("button", { name: "Edytuj: Masaż" }));
  dialog = await screen.findByRole("dialog", { name: "Edytuj usługę: Masaż" });
  expect(within(dialog).getByText("Produkty z magazynu")).toBeInTheDocument();
});
