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

import { ApiProblemError } from "@saas-core/api-client";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { BookingPanel } from "./booking-panel";
import { PublicBookingFlow } from "./public-booking-flow";
import { SelfServiceBooking } from "./self-service-booking";

const api = vi.hoisted(() => ({
  cancelBookingAppointment: vi.fn(),
  completeBookingAppointment: vi.fn(),
  listInventoryBalances: vi.fn(),
  listInventoryItems: vi.fn(),
  setBookingAppointmentMaterials: vi.fn(),
  createBookingAppointment: vi.fn(),
  createPublicBookingAppointment: vi.fn(),
  getBookingCatalog: vi.fn(),
  getBookingSlots: vi.fn(),
  getPublicBookingCatalog: vi.fn(),
  getPublicBookingSlots: vi.fn(),
  getSelfServiceBooking: vi.fn(),
  listBookingAppointments: vi.fn(),
  rescheduleBookingAppointment: vi.fn(),
  rescheduleSelfServiceBooking: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

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
    },
    {
      id: "33333333-3333-4333-8333-444444444444",
      name: "Check-up",
      public_slug: "check-up",
      duration_minutes: 60,
      appointment_kind: "",
    },
  ],
  resources: [{ id: ROOM, name: "Room", kind: "room" }],
};

// Thursday 20 August 2026, 10:00 in Warsaw; "today" is the day before.
const appointment = {
  id: "55555555-5555-4555-8555-555555555555",
  starts_at: "2026-08-20T08:00:00Z",
  ends_at: "2026-08-20T08:30:00Z",
  timezone: "Europe/Warsaw",
  service_name: "Consultation",
  status: "confirmed",
  customer_name: "Jan Kowalski",
  staff_id: ALEX,
  staff_name: "Alex",
  staff_membership_id: null,
  location_name: "Centrum",
  resource_name: "Room",
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
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ["Date"], shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-08-19T10:00:00Z"));
  api.getBookingCatalog.mockResolvedValue(catalog);
  api.getPublicBookingCatalog.mockResolvedValue(catalog);
  api.listBookingAppointments.mockResolvedValue([appointment, completed]);
  api.getPublicBookingSlots.mockResolvedValue({
    items: [
      {
        starts_at: "2026-08-20T08:00:00Z",
        ends_at: "2026-08-20T08:30:00Z",
        staff_id: ALEX,
        resource_id: ROOM,
      },
    ],
  });
  api.getSelfServiceBooking.mockResolvedValue(appointment);
  api.rescheduleSelfServiceBooking.mockResolvedValue({
    ...appointment,
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
    screen.queryByLabelText(messages.BookingConfiguration.kind),
  ).toBeNull();
  // Every status is spelled out in the legend, not only coloured.
  const legend = screen.getByRole("list", { name: messages.Calendar.legend });
  for (const label of Object.values(messages.Calendar.status))
    expect(within(legend).getByText(label)).not.toBeNull();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("views, navigation and filters show the right appointments", async () => {
  renderCalendar();
  await screen.findByText("Jan Kowalski");
  expect(
    screen.getByRole("heading", { level: 2, name: /^August 17\W+23, 2026$/ }),
  ).not.toBeNull();
  expect(screen.getByText("Anna Nowak")).not.toBeNull();

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
      name: "Thursday, August 20, 2026",
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
    expect(api.listBookingAppointments).toHaveBeenLastCalledWith({
      mine: true,
    }),
  );
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

  fireEvent.click(
    within(details).getByRole("button", { name: "Cancel appointment" }),
  );
  const confirm = await screen.findByRole("dialog", {
    name: "Cancel this appointment?",
  });
  expect(api.cancelBookingAppointment).not.toHaveBeenCalled();
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
  await waitFor(() =>
    expect(api.listBookingAppointments).toHaveBeenCalledTimes(2),
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
  api.listBookingAppointments.mockResolvedValue([
    { ...appointment, materials: [oil] },
    completed,
  ]);
  api.listInventoryItems.mockResolvedValue([
    { id: OIL, name: "Oil", active: true },
  ]);
  api.listInventoryBalances.mockResolvedValue([
    { item_id: OIL, available: "1.000" },
  ]);
  api.setBookingAppointmentMaterials.mockImplementation(
    (_id: string, materials: { quantity: string }[]) =>
      Promise.resolve({
        ...appointment,
        materials: [{ ...oil, quantity: materials[0].quantity }],
      }),
  );
  api.completeBookingAppointment.mockResolvedValue({
    ...appointment,
    status: "completed",
    materials: [oil],
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
  expect(await within(dialog).findByText("Free · Bea")).not.toBeNull();

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
  expect(await within(dialog).findByText("Free · Bea")).not.toBeNull();

  fireEvent.click(
    within(dialog).getByRole("button", { name: "Save appointment" }),
  );
  expect(
    await screen.findByText(/Appointment added: Ewa Zielińska/),
  ).not.toBeNull();
  const [input, key] = api.createBookingAppointment.mock.calls[1];
  expect(input).toEqual({
    service_id: catalog.services[0].id,
    location_id: catalog.locations[0].id,
    staff_id: BEA,
    resource_id: null,
    starts_at: "2026-08-20T09:00:00Z",
    customer: {
      display_name: "Ewa Zielińska",
      email: "",
      phone: "+48 600 100 200",
      locale: "en",
    },
  });
  // A retry of the same form keeps its idempotency key.
  expect(key).toBe(api.createBookingAppointment.mock.calls[0][1]);
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

test("public booking searches slots without requiring an account", async () => {
  render(
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      <PublicBookingFlow publicSlug="demo" />
    </NextIntlClientProvider>,
  );
  await screen.findByText("Consultation");
  fireEvent.change(screen.getByLabelText("Service"), {
    target: { value: catalog.services[0].id },
  });
  fireEvent.change(screen.getByLabelText("Location"), {
    target: { value: catalog.locations[0].id },
  });
  fireEvent.click(screen.getByRole("button", { name: "Show times" }));
  await waitFor(() => expect(api.getPublicBookingSlots).toHaveBeenCalledOnce());
  expect(await screen.findByRole("option", { name: /2026/ })).not.toBeNull();
});

test("self-service reschedules an active booking", async () => {
  render(
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      <SelfServiceBooking token="bk_test" />
    </NextIntlClientProvider>,
  );
  expect(await screen.findByText("Consultation")).not.toBeNull();
  fireEvent.change(screen.getByLabelText("New time"), {
    target: { value: "2026-08-21T10:00" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Reschedule" }));
  await waitFor(() =>
    expect(api.rescheduleSelfServiceBooking).toHaveBeenCalledOnce(),
  );
});
