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

import { ApiProblemError } from "@saas-core/api-client";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { BookingPanel } from "./booking-panel";
import { PublicBookingFlow } from "./public-booking-flow";
import { SelfServiceBooking } from "./self-service-booking";

const api = vi.hoisted(() => ({
  assignCrew: vi.fn(),
  cancelBookingAppointment: vi.fn(),
  completeBookingAppointment: vi.fn(),
  listInventoryBalances: vi.fn(),
  listInventoryItems: vi.fn(),
  setBookingAppointmentMaterials: vi.fn(),
  createBookingAppointment: vi.fn(),
  createPublicBookingAppointment: vi.fn(),
  getBookingCatalog: vi.fn(),
  getBookingSlots: vi.fn(),
  getCrewCandidates: vi.fn(),
  getPeopleDay: vi.fn(),
  getPublicBookingCatalog: vi.fn(),
  getPublicBookingDays: vi.fn(),
  getPublicBookingTimes: vi.fn(),
  getSelfServiceBooking: vi.fn(),
  listBookingAppointments: vi.fn(),
  listBookingPlaces: vi.fn(),
  listPeople: vi.fn(),
  listTeams: vi.fn(),
  markBookingAppointmentNoShow: vi.fn(),
  moveStay: vi.fn(),
  previewStayMove: vi.fn(),
  rescheduleBookingAppointment: vi.fn(),
  rescheduleSelfServiceBooking: vi.fn(),
  setBookingAppointmentPlace: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));
// A product's part of the calendar (ADR-067), for a kind core does not know.
const section = vi.hoisted(() => ({
  check: vi.fn(),
  save: vi.fn(),
  params: [] as unknown[],
}));
vi.mock("../../../product/calendar", () => ({
  default: {
    kinds: ["test.field"],
    formSection: (props: {
      params: Record<string, string>;
      errors: Record<string, string>;
      fill: (values: object) => void;
      onChange: (value: unknown) => void;
    }) => {
      section.params.push(props.params);
      return (
        <fieldset>
          <legend>Farm section</legend>
          <button
            onClick={() => {
              props.fill({
                customer: { display_name: "Jan Rolnik", phone: "600 700 800" },
                place: { town: "Wólka", address: "Polna 1" },
              });
              props.onChange({ farm: "farm-1" });
            }}
            type="button"
          >
            Pick the farm
          </button>
          <button
            onClick={() =>
              props.fill({
                customer: { display_name: "Ewa Nowak", phone: "", email: "" },
                place: { town: "Zalesie", address: "" },
              })
            }
            type="button"
          >
            Pick another farm
          </button>
          <button
            onClick={() => props.fill({ customer: { display_name: "Ola" } })}
            type="button"
          >
            Type a name
          </button>
          {props.errors.farm ? <p>{props.errors.farm}</p> : null}
        </fieldset>
      );
    },
    check: section.check,
    save: section.save,
    // A chosen farm gives the customer and the place (answer 50a).
    summarizes: (value: unknown) =>
      Boolean((value as { farm?: string } | undefined)?.farm),
    detailsSection: ({ appointment }: { appointment: { id: string } }) => (
      <p>Product details of {appointment.id}</p>
    ),
    // Also a service without a kind: the product turns such a visit into its own.
    detailsKinds: ["test.field", ""],
  },
}));
// The calendar reads its view from the address (plan: phase 2).
const address = vi.hoisted(() => ({ params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => address.params }));

const ALEX = "22222222-2222-4222-8222-222222222222";
const BEA = "22222222-2222-4222-8222-333333333333";
const ROOM = "44444444-4444-4444-8444-444444444444";

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
    {
      id: "33333333-3333-4333-8333-444444444444",
      name: "Check-up",
      public_slug: "check-up",
      duration_minutes: 60,
      appointment_kind: "",
      staff_count: 1,
      public_staff_choice: "none",
    },
  ],
  resources: [{ id: ROOM, name: "Room", kind: "room" }],
};
const FIELD = "33333333-3333-4333-8333-555555555555";
const ACCESS = {
  modules: [],
  permissions: null,
  isOwner: true,
  limited: false,
};

// Thursday 20 August 2026, 10:00 in Warsaw; "today" is the day before.
const appointment = {
  id: "55555555-5555-4555-8555-555555555555",
  starts_at: "2026-08-20T08:00:00Z",
  ends_at: "2026-08-20T08:30:00Z",
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
  resource_name: "Room",
  place: null,
  place_town: "",
  place_address: "",
  appointment_kind: "",
  flags: [],
  customer_phone: null,
  customer_email: null,
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
// What a customer is shown: when and where, never who (ADR-058 §8).
const publicAppointment = {
  id: appointment.id,
  starts_at: appointment.starts_at,
  ends_at: appointment.ends_at,
  timezone: appointment.timezone,
  service_name: appointment.service_name,
  location_name: appointment.location_name,
  status: appointment.status,
};
const completed = {
  ...appointment,
  id: "66666666-6666-4666-8666-666666666666",
  starts_at: "2026-08-21T12:00:00Z",
  ends_at: "2026-08-21T13:00:00Z",
  service_name: "Check-up",
  status: "completed",
  customer_name: "Anna Nowak",
  staff_id: BEA,
  staff_name: "Bea",
  resource_name: null,
  crew: [{ staff_id: BEA, name: "Bea", membership_id: null, lead: true }],
};

beforeEach(() => {
  vi.clearAllMocks();
  address.params = new URLSearchParams();
  window.history.replaceState(null, "", "/panel/calendar");
  vi.useFakeTimers({ toFake: ["Date"], shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-08-19T10:00:00Z"));
  api.getBookingCatalog.mockResolvedValue(catalog);
  api.getPublicBookingCatalog.mockResolvedValue({
    locations: catalog.locations,
    services: catalog.services,
    resources: catalog.resources,
    timezone: "Europe/Warsaw",
    online: { paused: false, resume_on: null },
  });
  api.listBookingAppointments.mockResolvedValue([appointment, completed]);
  api.listTeams.mockResolvedValue([]);
  // One person's day: the day view stays a list (the board is in day-board.test).
  api.listPeople.mockResolvedValue([]);
  api.getPeopleDay.mockResolvedValue({
    date: "2026-08-19",
    timezone: "Europe/Warsaw",
    items: [],
  });
  api.getPublicBookingDays.mockResolvedValue(["2026-08-20"]);
  api.getPublicBookingTimes.mockResolvedValue([
    { starts_at: "2026-08-20T08:00:00Z", ends_at: "2026-08-20T08:30:00Z" },
    { starts_at: "2026-08-20T08:30:00Z", ends_at: "2026-08-20T09:00:00Z" },
  ]);
  api.getSelfServiceBooking.mockResolvedValue(publicAppointment);
  api.rescheduleSelfServiceBooking.mockResolvedValue({
    ...publicAppointment,
    starts_at: "2026-08-21T08:00:00Z",
    ends_at: "2026-08-21T08:30:00Z",
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
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
] as const)("the calendar is accessible in %s", async (locale, messages) => {
  const rendered = renderCalendar({}, locale);
  expect(
    await screen.findByRole("heading", {
      level: 1,
      name: messages.Calendar.title,
    }),
  ).not.toBeNull();
  expect(await screen.findByText("Jan Kowalski")).not.toBeNull();
  // Setting up services is Settings' job; the calendar only links there.
  expect(
    screen
      .getByRole("link", { name: messages.Calendar.settingsLink })
      .getAttribute("href"),
  ).toBe("/panel/settings/services");
  expect(
    screen.queryByRole("button", { name: messages.ServicesSetup.addService }),
  ).toBeNull();
  // Every status is spelled out in the legend, not only coloured — „not
  // finished” only where a product closes its visits itself.
  const legend = screen.getByRole("list", { name: messages.Calendar.legend });
  for (const [status, label] of Object.entries(messages.Calendar.status))
    if (status !== "unclosed")
      expect(within(legend).getByText(label)).not.toBeNull();
  expect(
    within(legend).queryByText(messages.Calendar.status.unclosed),
  ).toBeNull();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("views, navigation and filters show the right appointments", async () => {
  renderCalendar();
  await screen.findByText("Jan Kowalski");
  expect(
    screen.getByRole("heading", { level: 2, name: /^Aug 17\W+23, 2026$/ }),
  ).not.toBeNull();
  expect(screen.getByText("Anna Nowak")).not.toBeNull();
  // Only the week on screen; whether there is any visit at all is asked apart.
  expect(api.listBookingAppointments).toHaveBeenCalledWith({
    from: "2026-08-17",
    to: "2026-08-24",
  });
  expect(api.listBookingAppointments).toHaveBeenCalledWith({ limit: 1 });

  fireEvent.change(screen.getByLabelText("Staff member"), {
    target: { value: BEA },
  });
  expect(screen.queryByText("Jan Kowalski")).toBeNull();
  fireEvent.change(screen.getByLabelText("Staff member"), {
    target: { value: "" },
  });
  fireEvent.change(screen.getByLabelText("Service"), {
    target: { value: "Consultation" },
  });
  expect(screen.queryByText("Anna Nowak")).toBeNull();
  fireEvent.change(screen.getByLabelText("Service"), {
    target: { value: "" },
  });

  fireEvent.click(screen.getByRole("button", { name: "Month" }));
  expect(
    screen.getByRole("heading", { level: 2, name: "August 2026" }),
  ).not.toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Thursday, August 20, 1 appointment" }),
  );
  expect(
    screen.getByRole("heading", {
      level: 2,
      name: "Thursday, Aug 20, 2026",
    }),
  ).not.toBeNull();
  expect(screen.getByText("Jan Kowalski")).not.toBeNull();
  expect(screen.queryByText("Anna Nowak")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "Next day" }));
  expect(screen.getByText("Anna Nowak")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Today" }));
  expect(screen.getByText("No appointments on this day.")).not.toBeNull();

  fireEvent.change(screen.getByLabelText("Staff member"), {
    target: { value: "mine" },
  });
  await waitFor(() =>
    expect(api.listBookingAppointments).toHaveBeenCalledWith({
      mine: true,
      from: "2026-08-19",
      to: "2026-08-20",
    }),
  );
  expect(window.location.search).toBe("?view=day&staff=mine");
});

test("the view, the day and the person come from the address and go back to it", async () => {
  address.params = new URLSearchParams(
    `view=list&date=2026-08-21&staff=${BEA}`,
  );
  renderCalendar();
  const table = await screen.findByRole("table", {
    name: "Visits: August 2026",
  });
  // A person's card links here: only their visits, in the month's list.
  expect(within(table).getByText("Anna Nowak")).not.toBeNull();
  expect(within(table).queryByText("Jan Kowalski")).toBeNull();
  expect(api.listBookingAppointments).toHaveBeenCalledWith({
    from: "2026-08-01",
    to: "2026-09-01",
  });
  fireEvent.click(screen.getByRole("button", { name: "Week" }));
  expect(window.location.search).toBe(`?date=2026-08-21&staff=${BEA}`);
});

test("planning a visit from a person's card opens the form with them chosen", async () => {
  address.params = new URLSearchParams(`new=1&staff=${ALEX}`);
  renderCalendar();
  const form = await screen.findByRole("dialog", { name: "New appointment" });
  const chosen = within(form).getByRole("list", { name: "Chosen people" });
  expect(within(chosen).getByText("Alex")).not.toBeNull();
  expect(
    within(chosen).getByRole("radio", { name: "Leads: Alex" }),
  ).toBeChecked();
});

test("the list is the month as a table, and a row opens the visit", async () => {
  renderCalendar();
  await screen.findByText("Jan Kowalski");
  fireEvent.click(screen.getByRole("button", { name: "List" }));
  expect(
    screen.getByRole("heading", { level: 2, name: "August 2026" }),
  ).not.toBeNull();
  const table = screen.getByRole("table", { name: "Visits: August 2026" });
  const rows = within(table).getAllByRole("row").slice(1);
  // In time order, as the month runs.
  expect(rows).toHaveLength(2);
  expect(rows[0]).toHaveTextContent("Jan Kowalski");
  expect(rows[1]).toHaveTextContent("Anna Nowak");
  // The staff filter narrows the list like every other view.
  fireEvent.change(screen.getByLabelText("Staff member"), {
    target: { value: BEA },
  });
  expect(within(table).queryByText("Jan Kowalski")).toBeNull();
  fireEvent.click(within(table).getByRole("button", { name: "Visit details" }));
  expect(
    await screen.findByRole("dialog", { name: /Anna Nowak/ }),
  ).not.toBeNull();
  // The arrows move the list by a month.
  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  fireEvent.click(screen.getByRole("button", { name: "Next month" }));
  expect(
    screen.getByRole("heading", { level: 2, name: "September 2026" }),
  ).not.toBeNull();
});

test("a visit's town shows in every view, and the list has a column for it", async () => {
  api.listBookingAppointments.mockResolvedValue([
    { ...appointment, place: "Wólka" },
    completed,
  ]);
  renderCalendar();
  const card = (await screen.findByText("Jan Kowalski")).closest("button");
  // Seen and spoken: a trimmer reads where to drive before whom.
  expect(card).toHaveTextContent("Wólka");
  expect(card).toHaveAccessibleName(/Town: Wólka/);
  expect(screen.getAllByText("Wólka")).toHaveLength(1);

  fireEvent.click(screen.getByRole("button", { name: "Month" }));
  expect(
    screen.getByRole("button", { name: /Jan Kowalski.*Town: Wólka/ }),
  ).not.toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "List" }));
  const table = screen.getByRole("table", { name: "Visits: August 2026" });
  expect(
    within(table).getByRole("columnheader", { name: "Location" }),
  ).not.toBeNull();
  expect(within(table).getAllByRole("row")[1]).toHaveTextContent("Wólka");
  // A visit without a place of its own: the location it is booked at (W5).
  expect(within(table).getAllByRole("row")[2]).toHaveTextContent("Centrum");

  fireEvent.click(
    within(table).getAllByRole("button", { name: "Visit details" })[0]!,
  );
  const details = await screen.findByRole("dialog", { name: /Jan Kowalski/ });
  expect(within(details).getByText("Wólka")).not.toBeNull();
});

test("when every visit is at the one location the list has no column for it", async () => {
  address.params = new URLSearchParams("view=list");
  renderCalendar();
  const table = await screen.findByRole("table", {
    name: "Visits: August 2026",
  });
  expect(
    within(table).queryByRole("columnheader", { name: "Location" }),
  ).toBeNull();
});

test("called-off visits wait behind „Show cancelled (n)” and leave the counts (UX-025)", async () => {
  api.listBookingAppointments.mockResolvedValue([
    appointment,
    {
      ...appointment,
      id: "a-canceled",
      customer_name: "Ola Odwołana",
      status: "canceled",
    },
  ]);
  renderCalendar();
  await screen.findByText("Jan Kowalski");
  expect(screen.queryByText("Ola Odwołana")).toBeNull();
  fireEvent.click(screen.getByRole("checkbox", { name: "Show cancelled (1)" }));
  expect(await screen.findByText("Ola Odwołana")).not.toBeNull();
});

test("a phone opens on the day, after the page has come from the server (48a, UX-032)", async () => {
  const original = window.matchMedia;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (query: string) => ({
      matches: query === "(max-width: 639px)",
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }),
  });
  try {
    renderCalendar({ viewKey: "phone-test" });
    expect(
      await screen.findByRole("button", { name: "Day", pressed: true }),
    ).not.toBeNull();
  } finally {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: original,
    });
  }
});

test("an appointment opens its details and is canceled only after confirmation", async () => {
  api.cancelBookingAppointment.mockResolvedValue({
    ...appointment,
    status: "canceled",
  });
  renderCalendar();
  fireEvent.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
  const details = await screen.findByRole("dialog", { name: "Jan Kowalski" });
  expect(within(details).getByText("Centrum")).not.toBeNull();
  expect(within(details).getByText("Room")).not.toBeNull();
  expect((await axe.run(details)).violations).toHaveLength(0);
  // Before its start nobody can say the customer did not come (UX-031).
  expect(
    within(details).queryByRole("button", { name: "Mark as no-show" }),
  ).toBeNull();

  fireEvent.click(
    within(details).getByRole("button", { name: "Cancel appointment" }),
  );
  const confirm = await screen.findByRole("dialog", {
    name: "Cancel this appointment?",
  });
  expect(api.cancelBookingAppointment).not.toHaveBeenCalled();
  // The reload after the change brings the visit as the server keeps it now.
  api.listBookingAppointments.mockResolvedValue([
    { ...appointment, status: "canceled" },
    completed,
  ]);
  fireEvent.click(
    within(confirm).getByRole("button", { name: "Yes, cancel it" }),
  );

  expect(
    await within(details).findByText("Appointment canceled."),
  ).not.toBeNull();
  expect(api.cancelBookingAppointment).toHaveBeenCalledWith(
    appointment.id,
    expect.stringMatching(/^[0-9a-f-]{36}$/),
  );
  expect(within(details).getByText("Canceled")).not.toBeNull();
  expect(
    within(details).queryByRole("button", { name: "Cancel appointment" }),
  ).toBeNull();
  // Its button is gone, so focus lands on the dialog's title, not the page.
  await waitFor(() =>
    expect(document.activeElement).toBe(
      within(details).getByRole("heading", { name: "Jan Kowalski" }),
    ),
  );
  // The change reloads the week and the "any visit at all" question.
  await waitFor(() =>
    expect(api.listBookingAppointments).toHaveBeenCalledTimes(4),
  );
});

test("a visit whose time is over shows apart, with no vacancy, and a no-show is asked first", async () => {
  // This morning, for two, one of them missing — and nobody closed it.
  const over = {
    ...appointment,
    starts_at: "2026-08-19T07:00:00Z",
    ends_at: "2026-08-19T07:30:00Z",
    passed: true,
    staff_required: 2,
    needs_assignment: true,
  };
  api.listBookingAppointments.mockResolvedValue([over]);
  api.markBookingAppointmentNoShow.mockResolvedValue({
    ...over,
    status: "no_show",
    passed: false,
    needs_assignment: false,
  });
  renderCalendar();
  const card = await screen.findByRole("button", { name: /Jan Kowalski/ });
  expect(within(card).getByText("Took place · to settle")).not.toBeNull();
  expect(within(card).queryByText("Vacancy")).toBeNull();

  fireEvent.click(card);
  const details = await screen.findByRole("dialog", { name: "Jan Kowalski" });
  expect(within(details).queryByText(/Vacancy/)).toBeNull();
  expect(
    within(details).getByRole("button", { name: "Complete the visit" }),
  ).not.toBeNull();
  fireEvent.click(
    within(details).getByRole("button", { name: "Mark as no-show" }),
  );
  const confirm = await screen.findByRole("dialog", {
    name: "Mark the customer as a no-show?",
  });
  expect(api.markBookingAppointmentNoShow).not.toHaveBeenCalled();
  expect((await axe.run(confirm)).violations).toHaveLength(0);
  // The reload after the change brings the visit as the server keeps it now.
  api.listBookingAppointments.mockResolvedValue([
    { ...over, status: "no_show", passed: false, needs_assignment: false },
  ]);
  fireEvent.click(
    within(confirm).getByRole("button", { name: "Yes, mark as no-show" }),
  );
  expect(
    await within(details).findByText("Marked as a no-show."),
  ).not.toBeNull();
  expect(api.markBookingAppointmentNoShow).toHaveBeenCalledWith(
    over.id,
    expect.stringMatching(/^[0-9a-f-]{36}$/),
  );
  expect(within(details).getByText("No-show")).not.toBeNull();
});

test("a stay changes its dates, not its slot: checked first, then moved", async () => {
  const stay = {
    ...appointment,
    time_model: "range",
    starts_at: "2026-08-20T14:00:00Z",
    ends_at: "2026-08-22T09:00:00Z",
    staff_id: null,
    staff_name: null,
    crew: [],
    staff_required: 0,
  };
  api.listBookingAppointments.mockResolvedValue([stay]);
  api.previewStayMove.mockResolvedValue({
    resource_id: "room",
    resource_name: "Room",
    starts_at: "2026-08-24T14:00:00Z",
    ends_at: "2026-08-26T09:00:00Z",
    length: 2,
    range_unit: "night",
  });
  api.moveStay.mockResolvedValue({
    ...stay,
    starts_at: "2026-08-24T14:00:00Z",
    ends_at: "2026-08-26T09:00:00Z",
  });
  renderCalendar();
  fireEvent.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
  const details = await screen.findByRole("dialog", { name: "Jan Kowalski" });
  expect(
    within(details).queryByRole("button", { name: "Reschedule" }),
  ).toBeNull();
  fireEvent.click(
    within(details).getByRole("button", { name: "Change dates" }),
  );
  const move = await screen.findByRole("dialog", { name: "Change dates" });
  fireEvent.change(within(move).getByLabelText(/New start/), {
    target: { value: "2026-08-24" },
  });
  fireEvent.change(within(move).getByLabelText(/New end/), {
    target: { value: "2026-08-26" },
  });
  expect(await within(move).findByText(/Room · 2 nights/)).toBeInTheDocument();
  fireEvent.click(within(move).getByRole("button", { name: "Move" }));
  await waitFor(() =>
    expect(api.moveStay).toHaveBeenCalledWith(
      stay.id,
      { start_date: "2026-08-24", end_date: "2026-08-26" },
      expect.stringMatching(/^[0-9a-f-]{36}$/),
    ),
  );
});

test("a visit's products can change until it is completed, which takes them off the shelf", async () => {
  const OIL = "77777777-7777-4777-8777-777777777777";
  const oil = {
    item_id: OIL,
    name: "Oil",
    unit: "piece",
    quantity: "2.000",
    mode: "sale",
    unit_price_minor: 4000,
    currency: "PLN",
  };
  // The server's copy of the visit: every reload brings what was saved.
  let visit = { ...appointment, materials: [oil] };
  api.listBookingAppointments.mockImplementation(async () => [
    visit,
    completed,
  ]);
  api.listInventoryItems.mockResolvedValue([
    { id: OIL, name: "Oil", active: true },
  ]);
  api.listInventoryBalances.mockResolvedValue([
    { item_id: OIL, available: "1.000" },
  ]);
  api.setBookingAppointmentMaterials.mockImplementation(
    async (_id: string, materials: { quantity: string }[]) => {
      visit = {
        ...visit,
        materials: [{ ...oil, quantity: materials[0].quantity }],
      };
      return visit;
    },
  );
  api.completeBookingAppointment.mockImplementation(async () => {
    visit = { ...visit, status: "completed", materials: [oil] };
    return visit;
  });
  renderCalendar({ canUseInventory: true });
  fireEvent.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
  const details = await screen.findByRole("dialog", { name: "Jan Kowalski" });
  expect(within(details).getByText(/Sales total/)).not.toBeNull();

  fireEvent.click(
    within(details).getByRole("button", { name: "Change products" }),
  );
  const quantity = await within(details).findByLabelText("Quantity");
  // Its own reservation (2) plus the free stock (1): three fit, four do not.
  fireEvent.change(quantity, { target: { value: "4" } });
  expect(within(details).getByText(/Only 3 free in stock/)).not.toBeNull();
  fireEvent.click(
    within(details).getByRole("button", { name: "Save products" }),
  );
  expect(
    await within(details).findByText("Visit products saved."),
  ).not.toBeNull();
  expect(api.setBookingAppointmentMaterials).toHaveBeenCalledWith(
    appointment.id,
    [{ item_id: OIL, quantity: "4", mode: "sale" }],
  );

  fireEvent.click(
    within(details).getByRole("button", { name: "Complete the visit" }),
  );
  expect(
    await within(details).findByText(
      "Visit completed. Its products left the warehouse.",
    ),
  ).not.toBeNull();
  expect(api.completeBookingAppointment).toHaveBeenCalledWith(
    appointment.id,
    expect.stringMatching(/^[0-9a-f-]{36}$/),
  );
  expect(
    within(details).queryByRole("button", { name: "Change products" }),
  ).toBeNull();
});

test("„Miejsce wizyty”: a saved place fills the town and the address, and a visit's place changes in its details", async () => {
  api.getBookingCatalog.mockResolvedValue({ ...catalog, place_search: true });
  api.listBookingPlaces.mockResolvedValue([
    { name: "Gospodarstwo Kowalski", town: "Testowo", address: "Polna 3" },
  ]);
  api.getBookingSlots.mockResolvedValue({
    items: [
      {
        starts_at: "2026-08-20T07:00:00Z",
        ends_at: "2026-08-20T07:30:00Z",
        staff_id: ALEX,
        resource_id: ROOM,
      },
    ],
  });
  api.createBookingAppointment.mockResolvedValue({
    ...appointment,
    place: "Testowo",
    place_town: "Testowo",
    place_address: "Polna 3",
  });
  renderCalendar();
  fireEvent.click(
    await screen.findByRole("button", { name: "New appointment" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "New appointment" });
  fireEvent.change(within(dialog).getByLabelText("Service"), {
    target: { value: catalog.services[0].id },
  });
  fireEvent.change(within(dialog).getByLabelText("Date"), {
    target: { value: "2026-08-20" },
  });
  fireEvent.change(within(dialog).getByLabelText("Time"), {
    target: { value: "09:00" },
  });
  fireEvent.change(within(dialog).getByLabelText("Full name"), {
    target: { value: "Jan Kowalski" },
  });
  fireEvent.change(within(dialog).getByLabelText("Phone"), {
    target: { value: "+48 600 100 200" },
  });
  const saved = await within(dialog).findByLabelText("Saved place");
  fireEvent.change(saved, { target: { value: "0" } });
  expect(within(dialog).getByLabelText("Town")).toHaveValue("Testowo");
  expect(
    within(dialog).getByLabelText("Address (street and number)"),
  ).toHaveValue("Polna 3");
  expect((await axe.run(dialog)).violations).toHaveLength(0);
  await waitFor(() =>
    expect(within(dialog).getByText("This time is free.")).not.toBeNull(),
  );
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Save appointment" }),
  );
  await waitFor(() => expect(api.createBookingAppointment).toHaveBeenCalled());
  expect(api.createBookingAppointment.mock.calls[0][0]).toMatchObject({
    place_town: "Testowo",
    place_address: "Polna 3",
  });

  // The visit's details: the place, and „Zmień miejsce” for whoever books.
  api.setBookingAppointmentPlace.mockResolvedValue({
    ...appointment,
    place: "Zambrów",
    place_town: "Zambrów",
    place_address: "",
  });
  fireEvent.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
  const details = await screen.findByRole("dialog", { name: /Jan Kowalski/ });
  expect(within(details).getByText("Not given")).not.toBeNull();
  fireEvent.click(
    within(details).getByRole("button", { name: "Change place" }),
  );
  fireEvent.change(within(details).getByLabelText("Town"), {
    target: { value: "Zambrów" },
  });
  fireEvent.click(within(details).getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(api.setBookingAppointmentPlace).toHaveBeenCalledWith(
      appointment.id,
      { town: "Zambrów", address: "" },
    ),
  );
  expect(await within(details).findByText("Visit place saved.")).not.toBeNull();
});

test("a product's kind of visit: its section fills the form and books the visit itself", async () => {
  address.params = new URLSearchParams(`new=1&service_id=${FIELD}&farm=farm-1`);
  api.getBookingCatalog.mockResolvedValue({
    ...catalog,
    services: [
      ...catalog.services,
      {
        ...catalog.services[0],
        id: FIELD,
        name: "Field visit",
        appointment_kind: "test.field",
      },
    ],
  });
  api.getBookingSlots.mockResolvedValue({
    items: [
      {
        starts_at: "2026-08-20T07:00:00Z",
        ends_at: "2026-08-20T07:30:00Z",
        staff_id: ALEX,
        resource_id: ROOM,
      },
    ],
  });
  section.check.mockReturnValueOnce({ farm: "Choose the farm." });
  section.check.mockReturnValue(null);
  section.save.mockResolvedValue({
    ...appointment,
    customer_name: "Jan Rolnik",
  });
  renderCalendar({ access: ACCESS });
  const dialog = await screen.findByRole("dialog", { name: "New appointment" });
  // The link named the service and the product's own parameter.
  expect(within(dialog).getByLabelText("Service")).toHaveValue(FIELD);
  expect(section.params).toContainEqual({ farm: "farm-1" });
  expect(window.location.search).toContain(`service_id=${FIELD}`);
  expect(window.location.search).toContain("farm=farm-1");

  // Another farm replaces the whole customer and place, not just what it names.
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Pick the farm" }),
  );
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Pick another farm" }),
  );
  expect(within(dialog).getByLabelText("Phone")).toHaveValue("");
  expect(
    within(dialog).getByLabelText("Address (street and number)"),
  ).toHaveValue("");
  // A key left out stays as typed: a card typed key by key wipes nothing.
  fireEvent.change(within(dialog).getByLabelText("Phone"), {
    target: { value: "600 999 999" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Type a name" }));
  expect(within(dialog).getByLabelText("Full name")).toHaveValue("Ola");
  expect(within(dialog).getByLabelText("Phone")).toHaveValue("600 999 999");
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Pick the farm" }),
  );
  expect(within(dialog).getByLabelText("Full name")).toHaveValue("Jan Rolnik");
  expect(within(dialog).getByLabelText("Town")).toHaveValue("Wólka");
  fireEvent.change(within(dialog).getByLabelText("Date"), {
    target: { value: "2026-08-20" },
  });
  fireEvent.change(within(dialog).getByLabelText("Time"), {
    target: { value: "09:00" },
  });
  await waitFor(() =>
    expect(within(dialog).getByText("This time is free.")).not.toBeNull(),
  );
  const save = within(dialog).getByRole("button", { name: "Save appointment" });
  fireEvent.click(save);
  // The section's own check holds the save and says where.
  expect(await within(dialog).findByText("Choose the farm.")).not.toBeNull();
  expect(section.save).not.toHaveBeenCalled();
  fireEvent.click(save);
  await waitFor(() => expect(section.save).toHaveBeenCalled());
  expect(section.save.mock.calls[0][0]).toMatchObject({
    input: {
      service_id: FIELD,
      place_town: "Wólka",
      place_address: "Polna 1",
      customer: { display_name: "Jan Rolnik", phone: "600 700 800" },
    },
    value: { farm: "farm-1" },
  });
  expect(api.createBookingAppointment).not.toHaveBeenCalled();
});

test("a chosen farm sums up the customer and the place; „Change for this visit” opens them", async () => {
  address.params = new URLSearchParams(`new=1&service_id=${FIELD}`);
  api.getBookingCatalog.mockResolvedValue({
    ...catalog,
    services: [
      ...catalog.services,
      {
        ...catalog.services[0],
        id: FIELD,
        name: "Field visit",
        appointment_kind: "test.field",
      },
    ],
  });
  api.getBookingSlots.mockResolvedValue({ items: [] });
  renderCalendar({ access: ACCESS });
  const dialog = await screen.findByRole("dialog", { name: "New appointment" });
  const fields = () =>
    within(dialog)
      .getByLabelText("Full name")
      .closest('[data-slot="customer-fields"]');
  expect(fields()?.className).not.toContain("hidden");

  fireEvent.click(
    within(dialog).getByRole("button", { name: "Pick the farm" }),
  );
  within(dialog).getByText("Jan Rolnik");
  within(dialog).getByText("600 700 800");
  within(dialog).getByText("Wólka, Polna 1");
  expect(fields()?.className).toContain("hidden");

  fireEvent.click(
    within(dialog).getByRole("button", { name: "Change for this visit" }),
  );
  expect(fields()?.className).not.toContain("hidden");
  expect(within(dialog).getByLabelText("Town")).toHaveValue("Wólka");
  expect(
    within(dialog).queryByRole("button", { name: "Change for this visit" }),
  ).toBeNull();
});

test("a link's farm belongs to the form it opened, not to the next one", async () => {
  address.params = new URLSearchParams(`new=1&service_id=${FIELD}&farm=farm-1`);
  api.getBookingCatalog.mockResolvedValue({
    ...catalog,
    services: [
      ...catalog.services,
      {
        ...catalog.services[0],
        id: FIELD,
        name: "Field visit",
        appointment_kind: "test.field",
      },
    ],
  });
  renderCalendar({ access: ACCESS });
  const first = await screen.findByRole("dialog", { name: "New appointment" });
  expect(within(first).getByLabelText("Service")).toHaveValue(FIELD);
  fireEvent.click(within(first).getByRole("button", { name: "Cancel" }));
  await waitFor(() =>
    expect(
      screen.queryByRole("dialog", { name: "New appointment" }),
    ).toBeNull(),
  );
  expect(window.location.search).not.toContain("farm=");
  fireEvent.click(screen.getByRole("button", { name: "New appointment" }));
  const second = await screen.findByRole("dialog", {
    name: "New appointment",
  });
  expect(within(second).getByLabelText("Service")).toHaveValue("");
  expect(window.location.search).not.toContain("farm=");
});

test("the server's word on a field is shown at that field", async () => {
  api.getBookingSlots.mockResolvedValue({
    items: [
      {
        starts_at: "2026-08-20T07:00:00Z",
        ends_at: "2026-08-20T07:30:00Z",
        staff_id: ALEX,
        resource_id: ROOM,
      },
    ],
  });
  api.createBookingAppointment.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Bad request",
      status: 400,
      code: "invalid",
      detail: { place_town: ["Podaj miejscowość do tej ulicy."] },
      correlation_id: null,
    }),
  );
  renderCalendar();
  fireEvent.click(
    await screen.findByRole("button", { name: "New appointment" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "New appointment" });
  fireEvent.change(within(dialog).getByLabelText("Service"), {
    target: { value: catalog.services[0].id },
  });
  fireEvent.change(within(dialog).getByLabelText("Date"), {
    target: { value: "2026-08-20" },
  });
  fireEvent.change(within(dialog).getByLabelText("Time"), {
    target: { value: "09:00" },
  });
  fireEvent.change(within(dialog).getByLabelText("Full name"), {
    target: { value: "Jan Kowalski" },
  });
  fireEvent.change(within(dialog).getByLabelText("Phone"), {
    target: { value: "600 100 200" },
  });
  fireEvent.change(
    within(dialog).getByLabelText("Address (street and number)"),
    { target: { value: "Polna 3" } },
  );
  await waitFor(() =>
    expect(within(dialog).getByText("This time is free.")).not.toBeNull(),
  );
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Save appointment" }),
  );
  expect(
    await within(dialog).findByText("Podaj miejscowość do tej ulicy."),
  ).not.toBeNull();
  expect(within(dialog).getByLabelText("Town")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
});

test("a visit's details: phone and e-mail to use, a map to the place, and the product's part", async () => {
  api.listBookingAppointments.mockResolvedValue([
    {
      ...appointment,
      appointment_kind: "test.field",
      customer_phone: "+48 600 100 200",
      customer_email: "jan@wies.test",
      place: "Wólka",
      place_town: "Wólka",
      place_address: "Polna 1",
      flags: ["farm_missing"],
    },
  ]);
  renderCalendar({ access: ACCESS });
  fireEvent.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
  const details = await screen.findByRole("dialog", { name: /Jan Kowalski/ });
  expect(
    within(details).getByRole("link", { name: /600 100 200/ }),
  ).toHaveAttribute("href", "tel:+48600100200");
  expect(
    within(details).getByRole("link", { name: "jan@wies.test" }),
  ).toHaveAttribute("href", "mailto:jan%40wies.test");
  expect(
    within(details)
      .getByRole("link", { name: /Navigate/ })
      .getAttribute("href"),
  ).toContain(encodeURIComponent("Wólka, Polna 1"));
  // A flag without the product's wording still reads, as its key.
  expect(within(details).getByText("farm_missing")).not.toBeNull();
  expect(
    within(details).getByText(`Product details of ${appointment.id}`),
  ).not.toBeNull();
});

test("a visit a module names goes by that name, the customer after it", async () => {
  api.listBookingAppointments.mockResolvedValue([
    { ...appointment, title: "Gospodarstwo Kowalski" },
  ]);
  renderCalendar({ access: ACCESS });
  const card = await screen.findByRole("button", {
    name: /Gospodarstwo Kowalski/,
  });
  expect(card).toHaveTextContent("Jan Kowalski");
  fireEvent.click(card);
  const details = await screen.findByRole("dialog", {
    name: /Gospodarstwo Kowalski/,
  });
  expect(within(details).getByText("Jan Kowalski")).not.toBeNull();
  // A booking of a service without a kind: the product's part is there too.
  expect(
    within(details).getByText(`Product details of ${appointment.id}`),
  ).not.toBeNull();
});

test("a new appointment takes a free time and says when one is taken", async () => {
  api.getBookingSlots.mockResolvedValue({
    items: [
      {
        starts_at: "2026-08-20T07:00:00Z",
        ends_at: "2026-08-20T07:30:00Z",
        staff_id: ALEX,
        resource_id: ROOM,
      },
      {
        starts_at: "2026-08-20T09:00:00Z",
        ends_at: "2026-08-20T09:30:00Z",
        staff_id: BEA,
        resource_id: null,
      },
    ],
  });
  api.createBookingAppointment
    .mockRejectedValueOnce(
      new ApiProblemError({
        type: "about:blank",
        title: "Conflict",
        status: 409,
        code: "slot_unavailable",
        detail: "Wybrany termin nie jest już dostępny.",
        correlation_id: null,
      }),
    )
    .mockResolvedValueOnce({
      ...appointment,
      id: "77777777-7777-4777-8777-777777777777",
      starts_at: "2026-08-20T09:00:00Z",
      ends_at: "2026-08-20T09:30:00Z",
      customer_name: "Ewa Zielińska",
      staff_id: BEA,
      staff_name: "Bea",
    });
  renderCalendar();
  fireEvent.click(
    await screen.findByRole("button", { name: "New appointment" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "New appointment" });

  fireEvent.change(within(dialog).getByLabelText("Service"), {
    target: { value: catalog.services[0].id },
  });
  fireEvent.change(within(dialog).getByLabelText("Date"), {
    target: { value: "2026-08-20" },
  });
  await waitFor(() =>
    expect(api.getBookingSlots).toHaveBeenLastCalledWith({
      service_id: catalog.services[0].id,
      location_id: catalog.locations[0].id,
      from: "2026-08-20",
      to: "2026-08-26",
    }),
  );
  fireEvent.change(within(dialog).getByLabelText("Time"), {
    target: { value: "10:00" },
  });
  expect(await within(dialog).findByText(/This time is taken/)).not.toBeNull();
  expect((await axe.run(dialog)).violations).toHaveLength(0);
  fireEvent.click(within(dialog).getByRole("button", { name: /11:00/ }));
  // "Any staff" is the server's pick, so the hint names nobody.
  expect(await within(dialog).findByText("This time is free.")).not.toBeNull();

  fireEvent.change(within(dialog).getByLabelText("Full name"), {
    target: { value: "Ewa Zielińska" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Save appointment" }),
  );
  expect(
    await within(dialog).findByText("Enter an email or a phone number."),
  ).not.toBeNull();
  expect(api.createBookingAppointment).not.toHaveBeenCalled();

  fireEvent.change(within(dialog).getByLabelText("Phone"), {
    target: { value: "+48 600 100 200" },
  });
  const searches = api.getBookingSlots.mock.calls.length;
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Save appointment" }),
  );
  expect(
    await within(dialog).findByText(
      "This time was just taken. Pick another one.",
    ),
  ).not.toBeNull();
  // The conflict refreshes the free times before the next try.
  await waitFor(() =>
    expect(api.getBookingSlots).toHaveBeenCalledTimes(searches + 1),
  );
  expect(await within(dialog).findByText("This time is free.")).not.toBeNull();

  fireEvent.click(
    within(dialog).getByRole("button", { name: "Save appointment" }),
  );
  expect(
    await screen.findByText(/Appointment added: Ewa Zielińska/),
  ).not.toBeNull();
  const [input, key] = api.createBookingAppointment.mock.calls[1];
  // Nobody was chosen, so nobody is named: the server picks (ADR-058 §4).
  expect(input).not.toHaveProperty("staff_id");
  expect(input).not.toHaveProperty("resource_id");
  expect(input).toEqual({
    service_id: catalog.services[0].id,
    location_id: catalog.locations[0].id,
    starts_at: "2026-08-20T09:00:00Z",
    // No language picked: the server takes the company's first, never the
    // panel's (ADR-071 pkt 21).
    customer: {
      display_name: "Ewa Zielińska",
      email: "",
      phone: "+48 600 100 200",
    },
  });
  // A retry of the same form keeps its idempotency key.
  expect(key).toBe(api.createBookingAppointment.mock.calls[0][1]);
});

test("a chosen staff member books with the resource that goes with them", async () => {
  api.getBookingSlots.mockResolvedValue({
    items: [
      {
        starts_at: "2026-08-20T07:00:00Z",
        ends_at: "2026-08-20T07:30:00Z",
        staff_id: ALEX,
        resource_id: ROOM,
      },
      {
        starts_at: "2026-08-20T07:00:00Z",
        ends_at: "2026-08-20T07:30:00Z",
        staff_id: BEA,
        resource_id: null,
      },
    ],
  });
  api.createBookingAppointment.mockResolvedValue({
    ...appointment,
    starts_at: "2026-08-20T07:00:00Z",
    ends_at: "2026-08-20T07:30:00Z",
    customer_name: "Ewa Zielińska",
  });
  renderCalendar();
  fireEvent.click(
    await screen.findByRole("button", { name: "New appointment" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "New appointment" });
  fireEvent.change(within(dialog).getByLabelText("Service"), {
    target: { value: catalog.services[0].id },
  });
  fireEvent.change(within(dialog).getByLabelText("Add a person or a team…"), {
    target: { value: ALEX },
  });
  fireEvent.change(within(dialog).getByLabelText("Date"), {
    target: { value: "2026-08-20" },
  });
  fireEvent.change(within(dialog).getByLabelText("Time"), {
    target: { value: "09:00" },
  });
  expect(await within(dialog).findByText("Free for: Alex.")).not.toBeNull();
  fireEvent.change(within(dialog).getByLabelText("Full name"), {
    target: { value: "Ewa Zielińska" },
  });
  fireEvent.change(within(dialog).getByLabelText("Phone"), {
    target: { value: "+48 600 100 200" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Save appointment" }),
  );
  await waitFor(() => expect(api.createBookingAppointment).toHaveBeenCalled());
  // The office chose Alex: the booking names Alex and Alex's room.
  expect(api.createBookingAppointment.mock.calls[0][0]).toMatchObject({
    staff_ids: [ALEX],
    resource_id: ROOM,
    starts_at: "2026-08-20T07:00:00Z",
  });
});

test("rescheduling offers the staff member's own free times", async () => {
  api.getBookingSlots.mockResolvedValue({
    items: [
      {
        starts_at: "2026-08-21T07:00:00Z",
        ends_at: "2026-08-21T07:30:00Z",
        staff_id: ALEX,
        resource_id: ROOM,
      },
      {
        starts_at: "2026-08-21T08:00:00Z",
        ends_at: "2026-08-21T08:30:00Z",
        staff_id: BEA,
        resource_id: null,
      },
    ],
  });
  api.rescheduleBookingAppointment.mockImplementation(
    async (_id: string, startsAt: string) => ({
      ...appointment,
      starts_at: startsAt,
      ends_at: new Date(Date.parse(startsAt) + 30 * 60_000).toISOString(),
    }),
  );
  renderCalendar();
  fireEvent.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
  const details = await screen.findByRole("dialog", { name: "Jan Kowalski" });
  fireEvent.click(within(details).getByRole("button", { name: "Reschedule" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Reschedule appointment",
  });
  await waitFor(() =>
    expect(api.getBookingSlots).toHaveBeenCalledWith({
      service_id: catalog.services[0].id,
      location_id: catalog.locations[0].id,
      from: "2026-08-20",
      to: "2026-08-26",
    }),
  );
  expect(
    await within(dialog).findByText(/There are no free times on this day/),
  ).not.toBeNull();
  fireEvent.click(within(dialog).getByRole("button", { name: /Aug 21/ }));
  expect(await within(dialog).findByText("This time is free.")).not.toBeNull();
  // Bea is free at 10:00, but a move keeps the staff member: not for Alex.
  fireEvent.change(within(dialog).getByLabelText("Time"), {
    target: { value: "10:00" },
  });
  expect(within(dialog).getByText(/This time is taken/)).not.toBeNull();

  // A time typed by hand is sent as the instant it means in the
  // organization's zone (CET in December, CEST in August).
  fireEvent.change(within(dialog).getByLabelText("Date"), {
    target: { value: "2026-12-01" },
  });
  fireEvent.change(within(dialog).getByLabelText("Time"), {
    target: { value: "10:00" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Save new time" }),
  );
  await waitFor(() =>
    expect(api.rescheduleBookingAppointment).toHaveBeenCalledWith(
      appointment.id,
      "2026-12-01T09:00:00.000Z",
      expect.any(String),
    ),
  );
  expect(
    await within(details).findByText(/Moved to Tue, December 1/),
  ).not.toBeNull();
});

const TEAM = "88888888-8888-4888-8888-888888888888";
const CARL = "22222222-2222-4222-8222-444444444444";

const candidate = (
  staffId: string,
  name: string,
  extra: Record<string, unknown> = {},
) => ({
  staff_id: staffId,
  name,
  team_ids: [TEAM],
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
  ...extra,
});

test("a visit's crew shows on its card and in its details, and the office staffs it", async () => {
  const short = {
    ...appointment,
    staff_required: 3,
    needs_assignment: true,
    crew_version: 4,
    crew: [
      { staff_id: ALEX, name: "Alex", membership_id: null, lead: true },
      { staff_id: BEA, name: "Bea", membership_id: null, lead: false },
    ],
    requested_team: { id: TEAM, name: "North" },
    customer_notes: "Gate code 1234",
  };
  api.listBookingAppointments.mockResolvedValue([short, completed]);
  api.listTeams.mockResolvedValue([
    { id: TEAM, name: "North", member_ids: [ALEX, BEA, CARL] },
  ]);
  api.getCrewCandidates.mockResolvedValue([
    candidate(ALEX, "Alex", { on_visit: true, lead: true }),
    candidate(BEA, "Bea", { on_visit: true }),
    candidate(CARL, "Carl"),
  ]);
  api.assignCrew.mockResolvedValue({
    ...short,
    needs_assignment: false,
    crew_version: 5,
    crew: [
      ...short.crew,
      { staff_id: CARL, name: "Carl", membership_id: null, lead: false },
    ],
  });
  renderCalendar();
  const card = await screen.findByRole("button", { name: /Jan Kowalski/ });
  // One name and a count for the eye, every name for a screen reader.
  expect(within(card).getByText("Alex +1")).not.toBeNull();
  expect(
    within(card).getByText("Consultation, Alex (lead), Bea, Centrum"),
  ).not.toBeNull();
  expect(within(card).getByText("Vacancy: 1 person missing")).not.toBeNull();
  // Bea helps on the visit she does not lead: her filter shows it too.
  fireEvent.change(screen.getByLabelText("Staff member"), {
    target: { value: BEA },
  });
  fireEvent.click(screen.getByRole("button", { name: /Jan Kowalski/ }));
  const details = await screen.findByRole("dialog", { name: "Jan Kowalski" });
  expect(within(details).getByText("Alex (lead), Bea")).not.toBeNull();
  expect(within(details).getByText("North")).not.toBeNull();
  expect(within(details).getByText("Gate code 1234")).not.toBeNull();
  expect((await axe.run(details)).violations).toHaveLength(0);

  fireEvent.click(
    within(details).getByRole("button", { name: "Assign people…" }),
  );
  const crew = await screen.findByRole("dialog", {
    name: "Assign — Jan Kowalski",
  });
  fireEvent.click(
    await within(crew).findByRole("checkbox", { name: "Pick: Carl" }),
  );
  fireEvent.click(within(crew).getByRole("button", { name: "Save crew" }));
  expect(await within(details).findByText("Crew saved.")).not.toBeNull();
  // The version the office looked at: a change made meanwhile is refused.
  expect(api.assignCrew).toHaveBeenCalledWith(
    short.id,
    {
      staff_ids: [ALEX, BEA, CARL],
      lead_id: ALEX,
      expected_version: 4,
      notify: true,
    },
    expect.stringMatching(/^[0-9a-f-]{36}$/),
  );
});

test("a lead taken off a visit that waits for somebody else is not on it any more", async () => {
  api.listBookingAppointments.mockResolvedValue([
    {
      ...appointment,
      needs_assignment: true,
      queue_reason: "time_off",
      crew: [],
    },
  ]);
  renderCalendar();
  await screen.findByRole("button", { name: /Jan Kowalski/ });
  fireEvent.change(screen.getByLabelText("Staff member"), {
    target: { value: ALEX },
  });
  expect(screen.queryByRole("button", { name: /Jan Kowalski/ })).toBeNull();
});

test("a visit for two is free only when both are, and books the crew named", async () => {
  const pair = {
    ...catalog.services[0],
    id: "33333333-3333-4333-8333-555555555555",
    name: "Pair work",
    staff_count: 2,
  };
  const slot = (startsAt: string, staffId: string) => ({
    starts_at: startsAt,
    ends_at: new Date(Date.parse(startsAt) + 30 * 60_000).toISOString(),
    staff_id: staffId,
    resource_id: ROOM,
  });
  api.getBookingCatalog.mockResolvedValue({ ...catalog, services: [pair] });
  api.listTeams.mockResolvedValue([
    { id: TEAM, name: "North", member_ids: [ALEX, BEA] },
  ]);
  api.getBookingSlots.mockResolvedValue({
    items: [
      slot("2026-08-20T07:00:00Z", ALEX),
      slot("2026-08-20T07:00:00Z", BEA),
      slot("2026-08-20T08:00:00Z", ALEX),
      slot("2026-08-21T07:00:00Z", ALEX),
      slot("2026-08-21T07:00:00Z", BEA),
    ],
  });
  api.createBookingAppointment.mockResolvedValue({
    ...appointment,
    customer_name: "Ewa Zielińska",
  });
  renderCalendar();
  fireEvent.click(
    await screen.findByRole("button", { name: "New appointment" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "New appointment" });
  expect(
    within(dialog).getByText("This service needs 2 people."),
  ).not.toBeNull();
  // Nobody named: the form says once what happens (UX plan W4).
  expect(
    within(dialog).getAllByText(
      "With nobody named we pick the least busy free people — you can change the crew later.",
    ),
  ).toHaveLength(1);
  fireEvent.change(within(dialog).getByLabelText("Date"), {
    target: { value: "2026-08-20" },
  });
  fireEvent.change(within(dialog).getByLabelText("Time"), {
    target: { value: "10:00" },
  });
  // Only Alex is free at 10:00; two are needed.
  expect(await within(dialog).findByText(/This time is taken/)).not.toBeNull();
  const add = within(dialog).getByLabelText("Add a person or a team…");
  expect(within(add).getByText("Alex — free at 10:00")).not.toBeNull();
  expect(within(add).getByText("Bea — not available at 10:00")).not.toBeNull();

  fireEvent.change(add, { target: { value: `team:${TEAM}` } });
  expect(
    within(dialog).getByText("Chosen from the team: North"),
  ).not.toBeNull();
  const chosen = within(dialog).getByRole("list", { name: "Chosen people" });
  fireEvent.click(within(chosen).getByRole("button", { name: "Remove: Bea" }));
  expect(
    within(dialog).getByText(
      "1 person missing — the visit goes to “To assign”.",
    ),
  ).not.toBeNull();
  fireEvent.change(add, { target: { value: BEA } });
  fireEvent.click(within(dialog).getByRole("button", { name: /^09:00/ }));
  expect(
    await within(dialog).findByText("Free for: Alex, Bea."),
  ).not.toBeNull();
  expect(
    within(dialog).getByText("Other times that suit them all:"),
  ).not.toBeNull();
  expect(within(dialog).getByRole("button", { name: /Aug 21/ })).not.toBeNull();
  expect((await axe.run(dialog)).violations).toHaveLength(0);

  fireEvent.change(within(dialog).getByLabelText("Full name"), {
    target: { value: "Ewa Zielińska" },
  });
  fireEvent.change(within(dialog).getByLabelText("Phone"), {
    target: { value: "+48 600 100 200" },
  });
  fireEvent.change(within(dialog).getByLabelText("Notes"), {
    target: { value: "  Gate code 1234 " },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Save appointment" }),
  );
  await waitFor(() => expect(api.createBookingAppointment).toHaveBeenCalled());
  expect(api.createBookingAppointment.mock.calls[0][0]).toMatchObject({
    service_id: pair.id,
    staff_ids: [ALEX, BEA],
    resource_id: ROOM,
    starts_at: "2026-08-20T07:00:00Z",
    customer_notes: "Gate code 1234",
  });
});

test("an empty calendar invites the first appointment, or the setup first", async () => {
  api.listBookingAppointments.mockResolvedValue([]);
  const rendered = renderCalendar();
  expect(
    await screen.findByText("Your calendar is still empty"),
  ).not.toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Plan the first appointment" }),
  );
  expect(
    await screen.findByRole("dialog", { name: "New appointment" }),
  ).not.toBeNull();
  rendered.unmount();

  api.getBookingCatalog.mockResolvedValue({ ...catalog, services: [] });
  renderCalendar();
  expect(
    await screen.findByText("Start with services and working hours"),
  ).not.toBeNull();
  expect(screen.queryByRole("button", { name: "New appointment" })).toBeNull();
});

test("without the manage permission the calendar is read-only", async () => {
  renderCalendar({ canManage: false });
  const card = await screen.findByRole("button", { name: /Jan Kowalski/ });
  card.focus();
  fireEvent.click(card);
  const details = await screen.findByRole("dialog", { name: "Jan Kowalski" });
  expect(
    within(details).queryByRole("button", { name: "Reschedule" }),
  ).toBeNull();
  expect(screen.queryByRole("button", { name: "New appointment" })).toBeNull();
  expect(
    screen.queryByRole("link", { name: "Services and schedule settings" }),
  ).toBeNull();
  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() => expect(document.activeElement).toBe(card));
});

test("load problems say what happened and what to do", async () => {
  api.listBookingAppointments.mockRejectedValueOnce(new Error("offline"));
  const rendered = renderCalendar();
  fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
  expect(await screen.findByText("Jan Kowalski")).not.toBeNull();
  rendered.unmount();

  api.listBookingAppointments.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Forbidden",
      status: 403,
      code: "entitlement_required",
      detail: "Plan organizacji nie pozwala na tę operację.",
      correlation_id: null,
    }),
  );
  renderCalendar();
  expect((await screen.findByRole("alert")).textContent).toContain(
    "The calendar isn't included in this organization's plan.",
  );
  expect(screen.getByRole("link", { name: "See the plan" })).not.toBeNull();
});

test("public booking picks a day, then a time, and names nobody", async () => {
  api.createPublicBookingAppointment.mockResolvedValue({
    ...publicAppointment,
    self_service_token: "bk_new",
  });
  render(
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      <PublicBookingFlow publicSlug="demo" />
    </NextIntlClientProvider>,
  );
  await screen.findByText("Consultation");
  fireEvent.change(screen.getByLabelText("Service"), {
    target: { value: catalog.services[0].id },
  });
  fireEvent.change(screen.getByLabelText("Place"), {
    target: { value: catalog.locations[0].id },
  });
  fireEvent.click(screen.getByRole("button", { name: "Show times" }));
  const query = {
    service_id: catalog.services[0].id,
    location_id: catalog.locations[0].id,
  };
  await waitFor(() =>
    expect(api.getPublicBookingDays).toHaveBeenCalledWith("demo", {
      ...query,
      from: "2026-08-19",
      to: "2026-09-02",
    }),
  );
  fireEvent.change(screen.getByLabelText("Day"), {
    target: { value: "2026-08-20" },
  });
  await waitFor(() =>
    expect(api.getPublicBookingTimes).toHaveBeenCalledWith("demo", {
      ...query,
      date: "2026-08-20",
    }),
  );
  // Each free start once, however many people are free at it.
  const time = screen.getByLabelText("Time");
  await waitFor(() =>
    expect(
      within(time)
        .getAllByRole("option")
        .map((option) => option.getAttribute("value")),
    ).toEqual(["", "2026-08-20T08:00:00Z", "2026-08-20T08:30:00Z"]),
  );
  // Booking without a time says what is missing instead of doing nothing.
  fireEvent.click(screen.getByRole("button", { name: "Book" }));
  expect(await screen.findByText("Choose a time.")).not.toBeNull();
  expect(screen.getByText("Enter a valid email address.")).not.toBeNull();
  expect(time.getAttribute("aria-invalid")).toBe("true");
  expect(api.createPublicBookingAppointment).not.toHaveBeenCalled();
  fireEvent.change(time, { target: { value: "2026-08-20T08:30:00Z" } });
  fireEvent.change(screen.getByLabelText("Full name"), {
    target: { value: "Anna Nowak" },
  });
  fireEvent.change(screen.getByLabelText("E-mail"), {
    target: { value: "anna@example.test" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Book" }));
  expect(await screen.findByText("Booking confirmed")).not.toBeNull();
  const [slug, input] = api.createPublicBookingAppointment.mock.calls[0];
  expect(slug).toBe("demo");
  expect(input).not.toHaveProperty("staff_id");
  expect(input).not.toHaveProperty("resource_id");
  expect(input).toEqual({
    ...query,
    starts_at: "2026-08-20T08:30:00Z",
    customer: {
      display_name: "Anna Nowak",
      email: "anna@example.test",
      phone: "",
      // The page's language, so an English customer gets English mail.
      locale: "en",
    },
  });
});

function renderPublic(locale: "en" | "pl" = "en") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "en" ? englishMessages : polishMessages}
    >
      <PublicBookingFlow publicSlug="demo" />
    </NextIntlClientProvider>,
  );
}

async function searchPublic(service = catalog.services[0].id) {
  await screen.findAllByText("Consultation");
  fireEvent.change(screen.getByLabelText(/Service|Usługa/), {
    target: { value: service },
  });
  fireEvent.change(screen.getByLabelText(/Place|Miejsce/), {
    target: { value: catalog.locations[0].id },
  });
  fireEvent.click(screen.getByRole("button", { name: /Show times|Pokaż/ }));
}

const options = (select: HTMLElement) =>
  within(select)
    .getAllByRole("option")
    .map((option) => option.textContent);

test("public times are the business's own clock, zone named", async () => {
  // 00:30 on 25 October in Warsaw, still the 24th in UTC; that night 02:30
  // happens twice (ADR-030).
  vi.setSystemTime(new Date("2026-10-24T22:30:00Z"));
  api.getPublicBookingDays.mockResolvedValue(["2026-10-25"]);
  api.getPublicBookingTimes.mockResolvedValue([
    { starts_at: "2026-10-25T00:30:00Z", ends_at: "2026-10-25T01:00:00Z" },
    { starts_at: "2026-10-25T01:30:00Z", ends_at: "2026-10-25T02:00:00Z" },
  ]);
  renderPublic("pl");
  await searchPublic();
  await waitFor(() =>
    expect(api.getPublicBookingDays).toHaveBeenCalledWith(
      "demo",
      expect.objectContaining({ from: "2026-10-25", to: "2026-11-08" }),
    ),
  );
  fireEvent.change(await screen.findByLabelText("Dzień"), {
    target: { value: "2026-10-25" },
  });
  await waitFor(() =>
    expect(options(screen.getByLabelText("Godzina"))).toEqual([
      "Wybierz",
      "02:30 CEST",
      "02:30 CET",
    ]),
  );
});

test("public times follow the latest choice and say when nothing is free", async () => {
  api.getPublicBookingDays.mockResolvedValue(["2026-08-20", "2026-08-21"]);
  let answerFirst: (value: unknown) => void = () => {};
  api.getPublicBookingTimes.mockImplementation(
    (_slug: string, { date }: { date: string }) =>
      date === "2026-08-20"
        ? new Promise((resolve) => {
            answerFirst = resolve;
          })
        : Promise.resolve([
            {
              starts_at: "2026-08-21T07:00:00Z",
              ends_at: "2026-08-21T07:30:00Z",
            },
          ]),
  );
  renderPublic();
  await searchPublic();
  const day = screen.getByLabelText("Day");
  await waitFor(() => expect(day).toHaveProperty("disabled", false));
  fireEvent.change(day, { target: { value: "2026-08-20" } });
  expect(await screen.findByText("Checking free times…")).not.toBeNull();
  fireEvent.change(day, { target: { value: "2026-08-21" } });
  const time = screen.getByLabelText("Time");
  await waitFor(() => expect(options(time)).toHaveLength(2));
  // The 20th answers last; the list stays the 21st's, the day on screen.
  await act(async () =>
    answerFirst([
      { starts_at: "2026-08-20T08:00:00Z", ends_at: "2026-08-20T08:30:00Z" },
    ]),
  );
  expect(
    within(time)
      .getAllByRole("option")
      .map((option) => option.getAttribute("value")),
  ).toEqual(["", "2026-08-21T07:00:00Z"]);
  fireEvent.change(time, { target: { value: "2026-08-21T07:00:00Z" } });

  // Another service: its days are still to be asked for.
  fireEvent.change(screen.getByLabelText("Service"), {
    target: { value: catalog.services[1].id },
  });
  expect(day).toHaveProperty("disabled", true);
  expect(options(time)).toEqual(["Choose"]);

  api.getPublicBookingDays.mockResolvedValue([]);
  fireEvent.click(screen.getByRole("button", { name: "Show times" }));
  expect(
    await screen.findByText("There are no free times in the next 14 days."),
  ).not.toBeNull();
  expect(day).toHaveProperty("disabled", true);
});

test("self-service reschedules an active booking", async () => {
  render(
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      <SelfServiceBooking token="bk_test" />
    </NextIntlClientProvider>,
  );
  expect(await screen.findByText("Consultation")).not.toBeNull();
  // Where, not who: the customer's page names no staff member.
  expect(screen.getByText("Centrum")).not.toBeNull();
  expect(screen.queryByText(/Alex/)).toBeNull();
  fireEvent.change(screen.getByLabelText("New time"), {
    target: { value: "2026-08-21T10:00" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Reschedule" }));
  await waitFor(() =>
    expect(api.rescheduleSelfServiceBooking).toHaveBeenCalledOnce(),
  );
});

test("„Do kogo?”: a chosen team narrows the times and goes with the booking and its notes", async () => {
  const NORTH = "88888888-8888-4888-8888-999999999999";
  api.getPublicBookingCatalog.mockResolvedValue({
    locations: catalog.locations,
    services: [
      {
        ...catalog.services[0],
        staff_choice: "team",
        team_ids: [NORTH],
        person_ids: [],
      },
    ],
    resources: [],
    teams: [{ id: NORTH, name: "Brygada Północ" }],
    people: [],
    timezone: "Europe/Warsaw",
    online: { paused: false, resume_on: null },
  });
  api.createPublicBookingAppointment.mockResolvedValue({
    ...publicAppointment,
    team_name: "Brygada Północ",
    person_name: null,
    self_service_token: "bk_new",
  });
  const rendered = render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <PublicBookingFlow publicSlug="demo" />
    </NextIntlClientProvider>,
  );
  await screen.findAllByText("Consultation");
  fireEvent.change(screen.getByLabelText("Usługa"), {
    target: { value: catalog.services[0].id },
  });
  fireEvent.change(screen.getByLabelText("Miejsce"), {
    target: { value: catalog.locations[0].id },
  });
  fireEvent.click(screen.getByLabelText("Wybrany zespół"));
  expect((screen.getByLabelText("Zespół") as HTMLSelectElement).value).toBe(
    NORTH,
  );
  fireEvent.click(screen.getByRole("button", { name: "Pokaż terminy" }));
  const query = {
    service_id: catalog.services[0].id,
    location_id: catalog.locations[0].id,
    team_id: NORTH,
  };
  await waitFor(() =>
    expect(api.getPublicBookingDays).toHaveBeenCalledWith(
      "demo",
      expect.objectContaining(query),
    ),
  );
  fireEvent.change(screen.getByLabelText("Dzień"), {
    target: { value: "2026-08-20" },
  });
  await waitFor(() =>
    expect(api.getPublicBookingTimes).toHaveBeenCalledWith("demo", {
      ...query,
      date: "2026-08-20",
    }),
  );
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("Godzina")).getAllByRole("option"),
    ).toHaveLength(3),
  );
  fireEvent.change(screen.getByLabelText("Godzina"), {
    target: { value: "2026-08-20T08:30:00Z" },
  });
  fireEvent.change(screen.getByLabelText("Imię i nazwisko"), {
    target: { value: "Stanisław Dąbrowski" },
  });
  fireEvent.change(screen.getByLabelText("E-mail"), {
    target: { value: "s@example.test" },
  });
  fireEvent.change(screen.getByLabelText("Uwagi"), {
    target: { value: " 120 krów, wjazd od silosu " },
  });
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Zarezerwuj" }));
  expect(await screen.findByText("Rezerwacja potwierdzona")).not.toBeNull();
  expect(api.createPublicBookingAppointment.mock.calls[0][1]).toMatchObject({
    team_id: NORTH,
    customer_notes: "120 krów, wjazd od silosu",
    starts_at: "2026-08-20T08:30:00Z",
  });
  // The confirmation says when, what and with whom, and gives the calendar file.
  expect(screen.getByText("Brygada Północ")).not.toBeNull();
  expect(
    screen.getByText(
      "Dziękujemy, Stanisław Dąbrowski. Potwierdzenie wysłaliśmy na s@example.test.",
    ),
  ).not.toBeNull();
  const file = screen.getByRole("link", { name: "Dodaj do kalendarza" });
  expect(file.getAttribute("href")).toMatch(/^data:text\/calendar/);
  expect(decodeURIComponent(file.getAttribute("href") ?? "")).toContain(
    "DTSTART:20260820T080000Z",
  );
  expect(
    screen.getByRole("link", { name: "Zmień termin lub odwołaj" }),
  ).toHaveAttribute("href", "/pl/booking/bk_new");
});

test("the customer's page names the person shown to customers", async () => {
  api.getSelfServiceBooking.mockResolvedValue({
    ...publicAppointment,
    team_name: null,
    person_name: "dr Anna Nowak",
  });
  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <SelfServiceBooking token="bk_test" />
    </NextIntlClientProvider>,
  );
  expect(await screen.findByText("Przyjmie Cię: dr Anna Nowak")).not.toBeNull();
});

test("a company that paused online booking says so instead of a form (ADR-078)", async () => {
  api.getPublicBookingCatalog.mockResolvedValue({
    locations: catalog.locations,
    services: catalog.services,
    resources: catalog.resources,
    timezone: "Europe/Warsaw",
    online: { paused: true, resume_on: "2026-09-01" },
  });
  renderPublic("pl");

  expect(
    await screen.findByText(
      "Rezerwacje online są wstrzymane — wracają 1 września 2026. Do tego czasu umów wizytę bezpośrednio z firmą.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Usługa")).toBeNull();
});
