import axe from "axe-core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { BookingPanel } from "./booking-panel";
import { PublicBookingFlow } from "./public-booking-flow";
import { SelfServiceBooking } from "./self-service-booking";

const api = vi.hoisted(() => ({
  cancelBookingAppointment: vi.fn(),
  createPublicBookingAppointment: vi.fn(),
  getBookingCatalog: vi.fn(),
  getPublicBookingCatalog: vi.fn(),
  getPublicBookingSlots: vi.fn(),
  getSelfServiceBooking: vi.fn(),
  listBookingAppointments: vi.fn(),
  rescheduleSelfServiceBooking: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const catalog = {
  locations: [
    {
      id: "11111111-1111-4111-8111-111111111111",
      name: "Centrum",
      public_slug: "centrum",
    },
  ],
  staff: [
    {
      id: "22222222-2222-4222-8222-222222222222",
      name: "Alex",
      public_slug: "alex",
    },
  ],
  services: [
    {
      id: "33333333-3333-4333-8333-333333333333",
      name: "Consultation",
      public_slug: "consultation",
      duration_minutes: 30,
    },
  ],
  resources: [
    { id: "44444444-4444-4444-8444-444444444444", name: "Room", kind: "room" },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  api.getBookingCatalog.mockResolvedValue(catalog);
  api.getPublicBookingCatalog.mockResolvedValue(catalog);
  api.listBookingAppointments.mockResolvedValue([
    {
      id: "55555555-5555-4555-8555-555555555555",
      starts_at: "2026-08-20T08:00:00Z",
      ends_at: "2026-08-20T08:30:00Z",
      timezone: "Europe/Warsaw",
      service_name: "Consultation",
      status: "confirmed",
      customer_name: "Jan",
      staff_name: "Alex",
      location_name: "Centrum",
      resource_name: "Room",
    },
  ]);
  api.getPublicBookingSlots.mockResolvedValue({
    items: [
      {
        starts_at: "2026-08-20T08:00:00Z",
        ends_at: "2026-08-20T08:30:00Z",
        staff_id: catalog.staff[0].id,
        resource_id: catalog.resources[0].id,
      },
    ],
  });
  api.getSelfServiceBooking.mockResolvedValue({
    id: "55555555-5555-4555-8555-555555555555",
    starts_at: "2026-08-20T08:00:00Z",
    ends_at: "2026-08-20T08:30:00Z",
    timezone: "Europe/Warsaw",
    service_name: "Consultation",
    status: "confirmed",
    customer_name: "Jan",
    staff_name: "Alex",
    location_name: "Centrum",
    resource_name: "Room",
  });
  api.rescheduleSelfServiceBooking.mockResolvedValue({
    id: "55555555-5555-4555-8555-555555555555",
    starts_at: "2026-08-21T08:00:00Z",
    ends_at: "2026-08-21T08:30:00Z",
    timezone: "Europe/Warsaw",
    service_name: "Consultation",
    status: "confirmed",
    customer_name: "Jan",
    staff_name: "Alex",
    location_name: "Centrum",
    resource_name: "Room",
  });
});

afterEach(cleanup);

test.each([
  ["pl", polishMessages],
  ["en", englishMessages],
] as const)("booking panel is accessible in %s", async (locale, messages) => {
  const rendered = render(
    <NextIntlClientProvider locale={locale} messages={messages}>
      <BookingPanel />
    </NextIntlClientProvider>,
  );
  expect(
    await screen.findByRole("heading", { name: messages.Booking.title }),
  ).not.toBeNull();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
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
