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

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { BookingPanel } from "./booking-panel";

const api = vi.hoisted(() => ({
  getBookingCatalog: vi.fn(),
  getBookingSlots: vi.fn(),
  getCrewCandidates: vi.fn(),
  getPeopleDay: vi.fn(),
  listBookingAppointments: vi.fn(),
  listPeople: vi.fn(),
  listTeams: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));
const address = vi.hoisted(() => ({ params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => address.params }));

const ALEX = "22222222-2222-4222-8222-222222222222";
const BEA = "22222222-2222-4222-8222-333333333333";
const TEAM = "77777777-7777-4777-8777-777777777777";

const catalog = {
  locations: [
    {
      id: "11111111-1111-4111-8111-111111111111",
      name: "Centrum",
      public_slug: "centrum",
    },
  ],
  staff: [
    { id: ALEX, name: "Alex", public_slug: "alex", membership_id: null },
    { id: BEA, name: "Bea", public_slug: "bea", membership_id: null },
  ],
  services: [
    {
      id: "33333333-3333-4333-8333-333333333333",
      name: "Consultation",
      public_slug: "consultation",
      duration_minutes: 30,
      appointment_kind: "",
      staff_count: 1,
      public_staff_choice: "none",
    },
  ],
  resources: [],
};

const person = (id: string, name: string) => ({
  id,
  name,
  public_slug: name.toLowerCase(),
  membership_id: null,
  invitation_id: null,
  phone: null,
  active: true,
  service_ids: [catalog.services[0].id],
  has_hours: true,
  team_ids: [TEAM],
  public_name: null,
  created_at: "2026-01-01T00:00:00Z",
});

// Wednesday 19 August 2026 in Warsaw (UTC+2); "now" is 12:00 there.
const visit = {
  id: "55555555-5555-4555-8555-555555555555",
  starts_at: "2026-08-19T11:00:00Z",
  ends_at: "2026-08-19T11:30:00Z",
  timezone: "Europe/Warsaw",
  service_name: "Consultation",
  status: "confirmed",
  passed: false,
  closes_explicitly: false,
  customer_name: "Jan Kowalski",
  title: "",
  staff_id: ALEX,
  staff_name: "Alex",
  staff_membership_id: null,
  location_name: "Centrum",
  place: null,
  place_town: "",
  place_address: "",
  appointment_kind: "",
  flags: [],
  customer_phone: null,
  customer_email: null,
  resource_name: null,
  crew: [{ staff_id: ALEX, name: "Alex", membership_id: null, lead: true }],
  staff_required: 1,
  needs_assignment: false,
  auto_assigned: false,
  crew_version: 1,
  queue_reason: "",
  queued_at: null,
  requested_team: null,
  requested_staff_id: null,
  customer_notes: "",
};
const vacancy = {
  ...visit,
  id: "66666666-6666-4666-8666-666666666666",
  starts_at: "2026-08-19T13:00:00Z",
  ends_at: "2026-08-19T13:30:00Z",
  customer_name: "Anna Nowak",
  crew: [],
  needs_assignment: true,
  queue_reason: "time_off",
};

const hours = (from: string, to: string) => ({ starts_at: from, ends_at: to });

beforeEach(() => {
  vi.clearAllMocks();
  address.params = new URLSearchParams("view=day");
  window.history.replaceState(null, "", "/panel/calendar");
  localStorage.clear();
  vi.useFakeTimers({ toFake: ["Date"], shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-08-19T10:00:00Z"));
  api.getBookingCatalog.mockResolvedValue(catalog);
  api.listBookingAppointments.mockResolvedValue([visit, vacancy]);
  api.listTeams.mockResolvedValue([
    { id: TEAM, name: "North", member_ids: [ALEX, BEA], created_at: "" },
  ]);
  api.listPeople.mockResolvedValue([person(ALEX, "Alex"), person(BEA, "Bea")]);
  api.getPeopleDay.mockResolvedValue({
    date: "2026-08-19",
    timezone: "Europe/Warsaw",
    items: [
      {
        staff_id: ALEX,
        // 08:00–16:00 local, the visit held 13:00–13:30.
        works: [hours("2026-08-19T06:00:00Z", "2026-08-19T14:00:00Z")],
        busy: [hours("2026-08-19T11:00:00Z", "2026-08-19T11:30:00Z")],
        time_off: [],
      },
      {
        staff_id: BEA,
        // 14:00–18:00 local.
        works: [hours("2026-08-19T12:00:00Z", "2026-08-19T16:00:00Z")],
        busy: [],
        time_off: [],
      },
    ],
  });
  api.getCrewCandidates.mockResolvedValue([]);
  api.getBookingSlots.mockResolvedValue({ slots: [] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  Reflect.deleteProperty(window, "matchMedia");
});

function renderCalendar(
  props: Parameters<typeof BookingPanel>[0] = {},
  locale: "en" | "pl" = "en",
) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "en" ? englishMessages : polishMessages}
      timeZone="Europe/Warsaw"
    >
      <BookingPanel timeZone="Europe/Warsaw" {...props} />
    </NextIntlClientProvider>,
  );
}

test.each([
  ["pl", polishMessages],
  ["en", englishMessages],
] as const)("the day board is accessible in %s", async (locale, messages) => {
  const rendered = renderCalendar({}, locale);
  expect(
    await screen.findByRole("region", { name: messages.DayBoard.label }),
  ).not.toBeNull();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("a row per person: where they are, their visits, and the day's vacancies above", async () => {
  renderCalendar();
  const board = await screen.findByRole("region", { name: "Day board" });
  expect(api.getPeopleDay).toHaveBeenCalledWith("2026-08-19");

  const alex = within(board).getByRole("group", { name: "Alex" });
  expect(
    within(alex).getByRole("button", { name: /13:00–13:30, Jan Kowalski/ }),
  ).not.toBeNull();
  // Now is 12:00: Alex has no visit until the 13:00 one, Bea's shift starts at 14:00.
  expect(within(board).getByText("No visit · next 13:00")).not.toBeNull();
  expect(within(board).getByText("Shift from 14:00")).not.toBeNull();
  expect(within(board).getAllByText("North")).toHaveLength(2);

  expect(within(board).getByText("To assign · 1")).not.toBeNull();
  fireEvent.click(
    within(board).getByRole("button", {
      name: "Assign people: Anna Nowak, Consultation, 15:00–15:30",
    }),
  );
  expect(await screen.findByRole("dialog")).not.toBeNull();
  await waitFor(() =>
    expect(api.getCrewCandidates).toHaveBeenCalledWith(vacancy.id, {
      everyone: false,
    }),
  );
});

test("a free window plans a visit for that person at that time", async () => {
  renderCalendar();
  const board = await screen.findByRole("region", { name: "Day board" });
  fireEvent.click(
    within(board).getByRole("button", {
      name: "Plan a visit: Bea, 14:00–18:00",
    }),
  );
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByLabelText("Date")).toHaveProperty(
    "value",
    "2026-08-19",
  );
  expect(within(dialog).getByLabelText("Time")).toHaveProperty(
    "value",
    "14:00",
  );
  expect(within(dialog).getByText("Bea")).not.toBeNull();
});

test("the filters narrow the rows; one person is the list, not a board", async () => {
  renderCalendar();
  const board = await screen.findByRole("region", { name: "Day board" });
  fireEvent.change(screen.getByLabelText("Staff member"), {
    target: { value: BEA },
  });
  expect(within(board).queryByRole("group", { name: "Alex" })).toBeNull();
  expect(within(board).getByRole("group", { name: "Bea" })).not.toBeNull();

  fireEvent.change(screen.getByLabelText("Staff member"), {
    target: { value: `team:${TEAM}` },
  });
  expect(within(board).getByRole("group", { name: "Alex" })).not.toBeNull();

  fireEvent.change(screen.getByLabelText("Staff member"), {
    target: { value: "" },
  });
  fireEvent.click(screen.getByLabelText("Only people working that day"));
  expect(within(board).getByRole("group", { name: "Alex" })).not.toBeNull();

  cleanup();
  api.getPeopleDay.mockResolvedValue({
    date: "2026-08-19",
    timezone: "Europe/Warsaw",
    items: [
      {
        staff_id: ALEX,
        works: [hours("2026-08-19T06:00:00Z", "2026-08-19T14:00:00Z")],
        busy: [],
        time_off: [],
      },
    ],
  });
  renderCalendar();
  expect(await screen.findByText("Jan Kowalski")).not.toBeNull();
  expect(screen.queryByRole("region", { name: "Day board" })).toBeNull();
});

test("on a phone the day is an agenda by person, vacancies first", async () => {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (query: string) => ({
      matches: query === "(max-width: 767px)",
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }),
  });
  renderCalendar();
  const agenda = await screen.findByRole("region", { name: "Day board" });
  const sections = within(agenda).getAllByRole("heading", { level: 3 });
  expect(sections.map((heading) => heading.textContent)).toEqual([
    "To assign · 1",
    "Alex",
    "Bea",
  ]);
  const alex = within(agenda).getByRole("region", { name: "Alex" });
  expect(within(alex).getByText("Jan Kowalski")).not.toBeNull();
  expect(within(alex).getByText("Free 13:30–16:00")).not.toBeNull();
  expect(
    within(agenda).getByRole("button", {
      name: "Plan a visit: Bea, 14:00–18:00",
    }),
  ).not.toBeNull();
  expect((await axe.run(agenda)).violations).toHaveLength(0);
});

test("the board and the agenda say in which town each visit is", async () => {
  api.listBookingAppointments.mockResolvedValue([
    { ...visit, place: "Wólka" },
    { ...vacancy, place: "Zalesie" },
  ]);
  renderCalendar();
  const board = await screen.findByRole("region", { name: "Day board" });
  expect(
    within(board).getByRole("button", {
      name: /13:00–13:30, Jan Kowalski, Wólka, Consultation/,
    }),
  ).toHaveTextContent("Wólka · 13:00–13:30");
  expect(
    within(board).getByRole("button", {
      name: "Assign people: Anna Nowak, Zalesie, Consultation, 15:00–15:30",
    }),
  ).toHaveTextContent("Zalesie · Consultation");
  cleanup();

  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (query: string) => ({
      matches: query === "(max-width: 767px)",
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }),
  });
  renderCalendar();
  const agenda = await screen.findByRole("region", { name: "Day board" });
  const alex = within(agenda).getByRole("region", { name: "Alex" });
  expect(
    within(alex).getByRole("button", { name: /Jan Kowalski Town: Wólka/ }),
  ).not.toBeNull();
  expect(within(agenda).getByText("Zalesie")).not.toBeNull();
});

test("the calendar opens on the view the person last chose here; a link still wins", async () => {
  address.params = new URLSearchParams();
  renderCalendar({ viewKey: "user-1" });
  await screen.findByText("Jan Kowalski");
  expect(screen.queryByRole("region", { name: "Day board" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Day" }));
  expect(
    await screen.findByRole("region", { name: "Day board" }),
  ).not.toBeNull();

  cleanup();
  renderCalendar({ viewKey: "user-1" });
  expect(
    await screen.findByRole("region", { name: "Day board" }),
  ).not.toBeNull();

  // Another person on this device keeps their own; a link names its view.
  cleanup();
  renderCalendar({ viewKey: "user-2" });
  await screen.findByText("Jan Kowalski");
  expect(screen.queryByRole("region", { name: "Day board" })).toBeNull();
  cleanup();
  address.params = new URLSearchParams("view=month");
  renderCalendar({ viewKey: "user-1" });
  expect(
    await screen.findByRole("heading", { level: 2, name: "August 2026" }),
  ).not.toBeNull();
});

test("whoever cannot assign gets no row to assign, and an empty day says why (UX-030)", async () => {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (query: string) => ({
      matches: query === "(max-width: 767px)",
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }),
  });
  address.params = new URLSearchParams("view=day&staff=");
  renderCalendar({ canManage: false });
  // The calendar opens on one's own visits; the board is the team's.
  fireEvent.change(await screen.findByLabelText("Staff member"), {
    target: { value: "" },
  });
  const agenda = await screen.findByRole("region", { name: "Day board" });
  expect(
    within(agenda)
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent),
  ).toEqual(["Alex", "Bea"]);
  const bea = within(agenda).getByRole("region", { name: "Bea" });
  expect(within(bea).getByText(/^No visits · works /)).not.toBeNull();
});
