import axe from "axe-core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type OrganizationSummary,
} from "@saas-core/api-client";

import englishMessages from "../../../../../messages/en.json";
import polishMessages from "../../../../../messages/pl.json";
import { PersonCard, type PersonTab } from "./person-card";

const api = vi.hoisted(() => ({
  addPerson: vi.fn(),
  addTimeOff: vi.fn(),
  getBookingCatalog: vi.fn(),
  getPeopleDay: vi.fn(),
  getPerson: vi.fn(),
  listBookingAppointments: vi.fn(),
  listInvitations: vi.fn(),
  listMemberships: vi.fn(),
  listPeople: vi.fn(),
  listRoles: vi.fn(),
  removeTimeOff: vi.fn(),
  setPersonHours: vi.fn(),
  setPersonServices: vi.fn(),
  updateMembership: vi.fn(),
  updatePerson: vi.fn(),
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const SERVICE = "0199c5f8-0000-7000-8000-000000000001";
const PLACE = "0199c5f8-0000-7000-8000-000000000002";
const viewer = [
  "organization.read",
  "notifications.preferences",
  "booking.appointment.read",
];
const owner = [
  ...viewer,
  "organization.members.read",
  "organization.members.manage_limited",
  "organization.members.manage",
  "organization.settings.manage",
  "booking.appointment.manage",
  "organization.ownership.transfer",
];

function organization(
  role: string,
  permissions: string[],
): OrganizationSummary {
  return {
    id: "019c5f87-fce8-739b-b960-b7a195bfc298",
    name: "Korekcja Racic Wójcik",
    slug: "wojcik",
    workspace_kind: "business",
    organization_type: "business",
    status: "active",
    default_locale: "pl",
    timezone: "Europe/Warsaw",
    currency: "PLN",
    version: 1,
    membership_status: "active",
    role,
    permissions,
    active: true,
  };
}

const detail = {
  id: "s-marcin",
  name: "Marcin Kowalski",
  public_slug: "marcin",
  membership_id: "marcin",
  invitation_id: null,
  phone: "601 234 567",
  active: true,
  service_ids: [SERVICE],
  has_hours: true,
  created_at: "2025-03-10T12:00:00Z",
  hours: [0, 1, 2, 3, 4].map((weekday) => ({
    id: `rule-${weekday}`,
    weekday,
    local_start: "06:00:00",
    local_end: "16:00:00",
    location_id: PLACE,
    location_name: "Baza",
  })),
  time_off: [
    {
      id: "off-1",
      starts_at: "2026-10-04T22:00:00Z",
      ends_at: "2026-10-06T22:00:00Z",
      reason: "Urlop",
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ["Date"], shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-09-24T08:30:00Z"));
  api.getPerson.mockResolvedValue(detail);
  api.listMemberships.mockResolvedValue([
    {
      id: "marcin",
      user_id: "user-marcin",
      email: "marcin@example.com",
      first_name: "Marcin",
      last_name: "Kowalski",
      role: "staff",
      status: "active",
      joined_at: "2025-03-10T12:00:00Z",
      revoked_at: null,
    },
  ]);
  api.listInvitations.mockResolvedValue([]);
  api.listRoles.mockResolvedValue({
    roles: [
      {
        key: "staff",
        name: "staff",
        scope: "system",
        permissions: [...viewer, "organization.members.read"],
        limited: true,
        version: 1,
      },
    ],
    grantable_permissions: [],
  });
  api.getBookingCatalog.mockResolvedValue({
    locations: [{ id: PLACE, name: "Baza", public_slug: "baza" }],
    staff: [],
    services: [
      {
        id: SERVICE,
        name: "Korekcja stada",
        public_slug: "korekcja",
        duration_minutes: 120,
        appointment_kind: "",
      },
    ],
    resources: [],
  });
  api.getPeopleDay.mockResolvedValue({
    date: "2026-09-24",
    timezone: "Europe/Warsaw",
    items: [
      {
        staff_id: "s-marcin",
        works: [
          {
            starts_at: "2026-09-24T04:00:00Z",
            ends_at: "2026-09-24T14:00:00Z",
          },
        ],
        time_off: [],
        busy: [
          {
            starts_at: "2026-09-24T06:00:00Z",
            ends_at: "2026-09-24T10:00:00Z",
          },
        ],
      },
    ],
  });
  api.listPeople.mockResolvedValue([]);
  api.listBookingAppointments.mockResolvedValue([
    {
      id: "visit-1",
      starts_at: "2026-09-28T05:00:00Z",
      ends_at: "2026-09-28T10:00:00Z",
      timezone: "Europe/Warsaw",
      service_name: "Korekcja stada",
      status: "confirmed",
      customer_name: "Gospodarstwo Kaczmarków",
      staff_id: "s-marcin",
      staff_name: "Marcin Kowalski",
      staff_membership_id: "marcin",
      location_name: "Baza",
      resource_name: null,
    },
  ]);
  api.setPersonHours.mockImplementation(async (_id, rules) => ({
    ...detail,
    hours: rules.map((rule: Record<string, unknown>, index: number) => ({
      id: `new-${index}`,
      ...rule,
      location_name: "Baza",
    })),
  }));
  api.addTimeOff.mockResolvedValue({
    time_off: {
      id: "off-2",
      starts_at: "2026-09-29T22:00:00Z",
      ends_at: "2026-10-01T22:00:00Z",
      reason: "",
    },
    conflicts: 1,
  });
  api.removeTimeOff.mockResolvedValue(undefined);
  api.updatePerson.mockResolvedValue(detail);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function renderCard(
  tab: PersonTab = "overview",
  current = organization("owner", owner),
  personId = "s-marcin",
  locale: "pl" | "en" = "pl",
) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <PersonCard
        access={{
          modules: ["shared.booking"],
          permissions: current.permissions,
          isOwner: current.role === "owner",
          limited: false,
          organizationType: "business",
        }}
        organization={current}
        personId={personId}
        tab={tab}
        user={
          {
            id: "user-owner",
            email: "jan@example.com",
            first_name: "Jan",
            last_name: "Wójcik",
          } as never
        }
      />
    </NextIntlClientProvider>,
  );
}

test("karta: dane, dziś, grafik i najbliższe wizyty z drogą do kalendarza", async () => {
  const { container } = renderCard();
  expect(
    await screen.findByRole("heading", { level: 1, name: "Marcin Kowalski" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Pracownik · w firmie od 10 marca 2025"),
  ).toBeInTheDocument();
  const facts = within(screen.getByRole("region", { name: "Dane pracownika" }));
  expect(facts.getByRole("link", { name: "601 234 567" })).toHaveAttribute(
    "href",
    "tel:601234567",
  );
  expect(facts.getByText("marcin@example.com")).toBeInTheDocument();
  expect(facts.getByText("Na wizycie do 12:00")).toBeInTheDocument();
  expect(facts.getByText("Korekcja stada")).toBeInTheDocument();
  expect(facts.getByText("Pn–Pt 06:00–16:00 · Baza")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Przegląd" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(screen.getByRole("link", { name: "Grafik" })).toHaveAttribute(
    "href",
    "/panel/team/s-marcin/schedule",
  );
  expect(screen.getByRole("link", { name: "Zaplanuj wizytę" })).toHaveAttribute(
    "href",
    "/panel/calendar?new=1&staff=s-marcin",
  );
  expect(
    screen.getByRole("link", { name: "Wszystkie w kalendarzu" }),
  ).toHaveAttribute("href", "/panel/calendar?view=list&staff=s-marcin");
  expect(screen.getByText("Gospodarstwo Kaczmarków")).toBeInTheDocument();
  // Two weeks ahead, only this person's visits.
  expect(api.listBookingAppointments).toHaveBeenCalledWith({
    staffId: "s-marcin",
    from: "2026-09-24",
    to: "2026-10-08",
  });
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("grafik: tydzień zapisuje się w całości, nieobecność to całe dni w strefie firmy", async () => {
  renderCard("schedule");
  expect(
    await screen.findByRole("heading", { name: "Godziny pracy" }),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Poniedziałek: od"), {
    target: { value: "07:00" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Dodaj godziny: Sobota" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Zapisz godziny pracy" }));
  await waitFor(() =>
    expect(api.setPersonHours).toHaveBeenCalledWith("s-marcin", [
      {
        weekday: 0,
        local_start: "07:00",
        local_end: "16:00",
        location_id: PLACE,
      },
      ...[1, 2, 3, 4].map((weekday) => ({
        weekday,
        local_start: "06:00",
        local_end: "16:00",
        location_id: PLACE,
      })),
      {
        weekday: 5,
        local_start: "08:00",
        local_end: "16:00",
        location_id: PLACE,
      },
    ]),
  );
  expect(
    await screen.findByText("Zapisano godziny pracy."),
  ).toBeInTheDocument();
  expect(screen.getByText("Urlop")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Dodaj nieobecność" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Nieobecność: Marcin Kowalski",
  });
  fireEvent.change(within(dialog).getByLabelText("Od dnia"), {
    target: { value: "2026-09-30" },
  });
  fireEvent.change(within(dialog).getByLabelText("Do dnia (włącznie)"), {
    target: { value: "2026-10-01" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz nieobecność" }),
  );
  // Warsaw's midnights: the first day's start to the day after the last.
  await waitFor(() =>
    expect(api.addTimeOff).toHaveBeenCalledWith("s-marcin", {
      starts_at: "2026-09-29T22:00:00.000Z",
      ends_at: "2026-10-01T22:00:00.000Z",
      reason: "",
    }),
  );
  expect(
    await screen.findByText(
      /W tym czasie Marcin Kowalski ma zaplanowane wizyty \(1\)/,
    ),
  ).toBeInTheDocument();

  // In time order: the new absence (30.09) comes before the holiday (5.10).
  fireEvent.click(
    screen.getAllByRole("button", { name: "Usuń nieobecność" })[1],
  );
  await waitFor(() => expect(api.removeTimeOff).toHaveBeenCalledWith("off-1"));
  expect(await screen.findByText("Usunięto nieobecność.")).toBeInTheDocument();
  expect(screen.queryByText("Urlop")).toBeNull();
});

test("moja karta: bez podglądu zespołu, własny telefon, grafik ustawia biuro", async () => {
  api.listPeople.mockResolvedValue([{ ...detail, hours: undefined }]);
  renderCard("overview", organization("viewer", viewer), "me");
  expect(
    await screen.findByRole("heading", { level: 1, name: "Marcin Kowalski" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Moja karta")).toBeInTheDocument();
  expect(api.listPeople).toHaveBeenCalledWith({ mine: true });
  // No team screen: no one else's data is asked for.
  expect(api.listMemberships).not.toHaveBeenCalled();
  // Without booking.schedule.own the office sets the hours (answer 7).
  expect(screen.queryByRole("button", { name: "Nieobecność" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Edytuj" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Edytuj: Marcin Kowalski",
  });
  expect(within(dialog).queryByLabelText("Imię i nazwisko")).toBeNull();
  fireEvent.change(within(dialog).getByLabelText("Telefon"), {
    target: { value: "605 000 111" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(api.updatePerson).toHaveBeenCalledWith("s-marcin", {
      phone: "605 000 111",
    }),
  );
});

test("moja karta bez wpisu w grafiku mówi, kogo poprosić", async () => {
  api.listPeople.mockResolvedValue([]);
  renderCard("overview", organization("viewer", viewer), "me");
  expect(
    await screen.findByText(/Nie masz jeszcze wpisu w grafiku firmy/),
  ).toBeInTheDocument();
  expect(api.getPerson).not.toHaveBeenCalled();
});

test("moja karta zarządu bez wpisu: konto z członkostwa, do grafiku dodaje się sam", async () => {
  api.listPeople.mockResolvedValue([]);
  api.listMemberships.mockResolvedValue([
    {
      id: "owner",
      user_id: "user-owner",
      email: "jan@example.com",
      first_name: "Jan",
      last_name: "Wójcik",
      role: "owner",
      status: "active",
      joined_at: "2024-01-15T12:00:00Z",
      revoked_at: null,
    },
  ]);
  api.addPerson.mockResolvedValue(detail);
  renderCard("overview", organization("owner", owner), "me");
  expect(
    await screen.findByText(/w firmie od 15 stycznia 2024/),
  ).toBeInTheDocument();
  expect(
    screen.queryByText(/Nie masz jeszcze wpisu w grafiku firmy/),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Edytuj" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Edytuj: Jan Wójcik",
  });
  fireEvent.click(within(dialog).getByLabelText("Korekcja stada"));
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(api.addPerson).toHaveBeenCalledWith({
      name: "Jan Wójcik",
      phone: "",
      membership_id: "owner",
      service_ids: [SERVICE],
    }),
  );
});

test("bez kalendarza w planie karta to samo konto: bez edycji i bez grafiku", async () => {
  const outsidePlan = new ApiProblemError({
    type: "about:blank",
    title: "Forbidden",
    status: 403,
    code: "entitlement_required",
    detail: "Moduł nie jest dostępny w planie organizacji.",
    correlation_id: null,
  });
  api.getPerson.mockRejectedValue(outsidePlan);
  api.getBookingCatalog.mockRejectedValue(outsidePlan);
  api.listPeople.mockRejectedValue(outsidePlan);
  renderCard("overview", organization("owner", owner), "marcin");
  expect(
    await screen.findByRole("heading", { level: 1, name: "Marcin Kowalski" }),
  ).toBeInTheDocument();
  // The role is the core's and stays; the entry would need the calendar.
  expect(
    screen.getByRole("button", { name: "Zmień rolę" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Edytuj" })).toBeNull();
  cleanup();

  renderCard("overview", organization("viewer", viewer), "me");
  expect(
    await screen.findByRole("heading", { level: 1, name: "Jan Wójcik" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByText(/Nie masz jeszcze wpisu w grafiku firmy/),
  ).toBeNull();
});

test("cudza albo nieistniejąca osoba to jasny komunikat, nie błąd (EN)", async () => {
  api.getPerson.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Not found",
      status: 404,
      code: "not_found",
      detail: "Nie ma takiego pracownika.",
      correlation_id: null,
    }),
  );
  api.listMemberships.mockResolvedValue([]);
  renderCard("overview", organization("owner", owner), "someone", "en");
  expect(
    await screen.findByText(
      "There is no such person, or you may not see them.",
    ),
  ).toBeInTheDocument();
});
