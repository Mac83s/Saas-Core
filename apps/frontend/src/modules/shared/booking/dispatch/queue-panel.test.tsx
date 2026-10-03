import axe from "axe-core";
import {
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
import { QueuePanel } from "./queue-panel";

const { api, router } = vi.hoisted(() => ({
  api: {
    assignCrew: vi.fn(),
    getBookingQueue: vi.fn(),
    getCrewCandidates: vi.fn(),
    listTeams: vi.fn(),
  },
  router: { refresh: vi.fn() },
}));
vi.mock("#i18n/navigation", () => ({ Link: "a", useRouter: () => router }));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const MARCIN = "22222222-2222-4222-8222-222222222222";
const PIOTR = "22222222-2222-4222-8222-333333333333";
const KRZYSZTOF = "22222222-2222-4222-8222-444444444444";

const member = (staffId: string, name: string, lead = false) => ({
  staff_id: staffId,
  name,
  membership_id: null,
  lead,
});

// Tomorrow 07:00 in Warsaw, picked by the system from the website.
const picked = {
  id: "55555555-5555-4555-8555-555555555555",
  starts_at: "2026-09-25T05:00:00Z",
  ends_at: "2026-09-25T10:00:00Z",
  timezone: "Europe/Warsaw",
  service_name: "Korekcja stada",
  status: "confirmed",
  passed: false,
  closes_explicitly: false,
  customer_name: "Gospodarstwo Kaczmarków",
  title: "",
  staff_id: MARCIN,
  staff_name: "Marcin Kowalski",
  staff_membership_id: null,
  location_name: "Baza",
  place: null,
  place_town: "",
  place_address: "",
  appointment_kind: "",
  flags: [],
  resource_name: null,
  crew: [
    member(MARCIN, "Marcin Kowalski", true),
    member(PIOTR, "Piotr Wiśniewski"),
  ],
  staff_required: 2,
  needs_assignment: false,
  auto_assigned: true,
  crew_version: 1,
  queue_reason: "public",
  queued_at: "2026-09-24T07:30:00Z",
  requested_team: null,
  requested_staff_id: null,
  customer_notes: "64 krowy",
  customer_phone: "609 321 654",
  customer_email: "",
};
// Next week: Tomasz went on leave and his place is empty.
const vacancy = {
  ...picked,
  id: "66666666-6666-4666-8666-666666666666",
  starts_at: "2026-09-30T11:30:00Z",
  ends_at: "2026-09-30T13:30:00Z",
  service_name: "Kontrola i opatrunki",
  customer_name: "Ferma Lipowa",
  staff_id: KRZYSZTOF,
  crew: [member(KRZYSZTOF, "Krzysztof Nowak", true)],
  needs_assignment: true,
  auto_assigned: false,
  crew_version: 3,
  queue_reason: "time_off",
  queued_at: "2026-09-22T08:30:00Z",
  customer_notes: "",
};

const organization = (permissions: string[]): OrganizationSummary => ({
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
  role: "manager",
  permissions,
  active: true,
});

const office = organization([
  "booking.appointment.read",
  "booking.appointment.manage",
]);

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ["Date"], shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-09-24T08:30:00Z"));
  api.getBookingQueue.mockResolvedValue([picked, vacancy]);
  api.listTeams.mockResolvedValue([]);
  api.assignCrew.mockResolvedValue({ ...picked, auto_assigned: false });
  api.getCrewCandidates.mockResolvedValue([
    {
      staff_id: KRZYSZTOF,
      name: "Krzysztof Nowak",
      team_ids: [],
      account: "none",
      phone: "604 567 890",
      does_service: true,
      state: "free",
      until: null,
      hours: [],
      on_visit: true,
      lead: true,
      day_visits: 1,
      day_minutes: 120,
      next_free: null,
    },
    {
      staff_id: PIOTR,
      name: "Piotr Wiśniewski",
      team_ids: [],
      account: "active",
      phone: null,
      does_service: true,
      state: "free",
      until: null,
      hours: [],
      on_visit: false,
      lead: false,
      day_visits: 0,
      day_minutes: 0,
      next_free: null,
    },
  ]);
});

afterEach(() => {
  vi.useRealTimers();
});

function renderQueue(current = office, locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <QueuePanel organization={current} />
    </NextIntlClientProvider>,
  );
}

test("kolejka: dobór systemu i wakat, skąd i od kiedy czekają, z uwagami klienta", async () => {
  const { container } = renderQueue();
  const table = await screen.findByRole("table", {
    name: "Wizyty do przydzielenia",
  });
  const first = within(table)
    .getByText("Gospodarstwo Kaczmarków")
    .closest("tr")!;
  expect(within(first).getByText("jutro")).toBeInTheDocument();
  expect(within(first).getByText("„64 krowy”")).toBeInTheDocument();
  expect(
    within(first).getByText("Marcin Kowalski, Piotr Wiśniewski"),
  ).toBeInTheDocument();
  expect(within(first).getByText("Dobrano automatycznie")).toBeInTheDocument();
  expect(within(first).getByText("od 1 h")).toBeInTheDocument();
  expect(within(first).getByText("Strona")).toBeInTheDocument();
  const second = within(table).getByText("Ferma Lipowa").closest("tr")!;
  expect(
    within(second).getByText("Wakat: brakuje 1 osoby"),
  ).toBeInTheDocument();
  expect(
    within(second).getByText("Nieobecność · wróciło z przydziału"),
  ).toBeInTheDocument();
  // A vacancy has no pick to keep.
  expect(
    within(second).queryByRole("button", { name: /Zostaw skład/ }),
  ).toBeNull();

  fireEvent.change(screen.getByLabelText("Rodzaj"), {
    target: { value: "vacancy" },
  });
  expect(within(table).queryByText("Gospodarstwo Kaczmarków")).toBeNull();
  fireEvent.change(screen.getByLabelText("Rodzaj"), { target: { value: "" } });
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("„Zostaw” zatwierdza dobór bez powiadamiania nikogo", async () => {
  renderQueue();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Zostaw skład: Gospodarstwo Kaczmarków",
    }),
  );
  expect(
    await screen.findByText("Zostawiono skład: Gospodarstwo Kaczmarków."),
  ).toBeInTheDocument();
  expect(api.assignCrew).toHaveBeenCalledWith(
    picked.id,
    {
      staff_ids: [MARCIN, PIOTR],
      lead_id: MARCIN,
      expected_version: 1,
      notify: false,
    },
    expect.stringMatching(/^[0-9a-f-]{36}$/),
  );
  await waitFor(() => expect(api.getBookingQueue).toHaveBeenCalledTimes(2));
  expect(router.refresh).toHaveBeenCalled();
});

test("a crew changed meanwhile names who did it and the list is fetched again (EN)", async () => {
  api.assignCrew.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      code: "crew_changed",
      detail:
        "Skład tej wizyty zmienił w międzyczasie: Anna Lewandowska. Odśwież i spróbuj ponownie.",
      correlation_id: null,
    }),
  );
  renderQueue(office, "en");
  fireEvent.click(
    await screen.findByRole("button", { name: "Assign: Ferma Lipowa" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Assign — Ferma Lipowa",
  });
  fireEvent.click(
    await within(dialog).findByRole("checkbox", {
      name: "Pick: Piotr Wiśniewski",
    }),
  );
  expect(within(dialog).getByRole("status")).toHaveTextContent(
    "2 of 2 chosen · Krzysztof Nowak leads",
  );
  fireEvent.click(within(dialog).getByRole("button", { name: "Save crew" }));
  // The server names who changed it; the dialog stays, the list reloads.
  expect((await within(dialog).findByRole("alert")).textContent).toContain(
    "Anna Lewandowska",
  );
  expect(api.assignCrew).toHaveBeenCalledWith(
    vacancy.id,
    expect.objectContaining({
      staff_ids: [KRZYSZTOF, PIOTR],
      lead_id: KRZYSZTOF,
      expected_version: 3,
      notify: true,
    }),
    expect.any(String),
  );
  await waitFor(() => expect(api.getBookingQueue).toHaveBeenCalledTimes(2));
});

test("bez zarządzania wizytami kolejka nic nie pobiera", () => {
  renderQueue(organization(["booking.appointment.read"]));
  expect(
    screen.getByText("Przydzielanie wizyt należy do zarządu i biura."),
  ).toBeInTheDocument();
  expect(api.getBookingQueue).not.toHaveBeenCalled();
});
