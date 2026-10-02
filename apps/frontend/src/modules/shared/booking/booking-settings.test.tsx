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
  createSetupLocation: vi.fn(),
  createSetupResource: vi.fn(),
  createSetupService: vi.fn(),
  getBookingSetup: vi.fn(),
  listInventoryBalances: vi.fn(),
  listInventoryItems: vi.fn(),
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
const OLD = "33333333-3333-4333-8333-444444444444";

const service = (over: Record<string, unknown>) => ({
  id: HERD,
  name: "Korekcja stada 60–150 krów",
  appointment_kind: "",
  duration_minutes: 90,
  buffer_before_minutes: 0,
  buffer_after_minutes: 30,
  minimum_notice_minutes: 60,
  staff_count: 2,
  public_staff_choice: "team",
  active: true,
  staff_ids: [MARCIN, PIOTR],
  location_ids: [BASE],
  resource_ids: [],
  materials: [],
  takes_materials: true,
  version: 3,
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
  resources: [{ id: ROOM, name: "Poskrom", active: true, version: 1 }],
  staff: [
    { id: MARCIN, name: "Marcin Kowalski", hours_version: 1 },
    { id: PIOTR, name: "Piotr Wiśniewski", hours_version: 1 },
  ],
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
});

test("usługi, miejsca i zasoby w listach, z tym, co trzeba poprawić", async () => {
  const { container } = renderSettings();
  const services = await screen.findByRole("table", { name: "Usługi firmy" });
  const herd = within(services)
    .getByText("Korekcja stada 60–150 krów")
    .closest("tr")!;
  expect(within(herd).getByText("1 h 30 min")).toBeInTheDocument();
  expect(within(herd).getByText("2 osoby")).toBeInTheDocument();
  expect(within(herd).getByText("od razu · wybór: zespół")).toBeInTheDocument();
  const old = within(services).getByText("Wizyta interwencyjna").closest("tr")!;
  expect(within(old).getByText("Wyłączona")).toBeInTheDocument();
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
    screen.getByRole("link", { name: "Przejdź do Zespół › Pracownicy" }),
  ).toHaveAttribute("href", "/panel/team");
  expect((await axe.run(container, noContrast)).violations).toEqual([]);
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
      duration_minutes: 90,
      buffer_before_minutes: 0,
      buffer_after_minutes: 30,
      minimum_notice_minutes: 60,
      staff_count: 2,
      public_staff_choice: "team",
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
      { name: "Gabinet Toruń", address: "ul. Długa 2" },
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
