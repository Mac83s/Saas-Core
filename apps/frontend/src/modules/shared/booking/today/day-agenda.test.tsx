import axe from "axe-core";
import { cleanup, render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import polishMessages from "../../../../../messages/pl.json";
import type { PanelAccess } from "#lib/panel-navigation";
import { DayAgenda } from "./day-agenda";

const api = vi.hoisted(() => ({
  getBookingQueue: vi.fn(),
  listBookingAppointments: vi.fn(),
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

// Thursday 1 October 2026, 09:00 in Warsaw.
const NOW = new Date("2026-10-01T07:00:00Z");

const visit = (fields: Record<string, unknown>) => ({
  id: crypto.randomUUID(),
  starts_at: "2026-10-01T08:00:00Z",
  ends_at: "2026-10-01T09:00:00Z",
  timezone: "Europe/Warsaw",
  service_name: "Strzyżenie",
  status: "confirmed",
  customer_name: "Joanna Nowak",
  title: "",
  staff_name: "Paweł",
  location_name: "Centrum",
  place: null,
  ...fields,
});

function access(permissions: string[]): PanelAccess {
  return {
    modules: ["core.organizations", "shared.booking"],
    permissions,
    isOwner: false,
    limited: false,
    organizationType: "business",
  };
}

function view(permissions: string[]) {
  return render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <DayAgenda access={access(permissions)} timeZone="Europe/Warsaw" />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  api.getBookingQueue.mockResolvedValue([{ id: "a" }, { id: "b" }]);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

test("whoever plans visits sees the company's today and tomorrow, and the queue", async () => {
  api.listBookingAppointments.mockResolvedValue([
    visit({ title: "Gospodarstwo Mazur", place: "Zambrów" }),
    visit({ customer_name: "Odwołana", status: "canceled" }),
    visit({
      customer_name: "Ewa Kowalczyk",
      starts_at: "2026-10-02T12:00:00Z",
      ends_at: "2026-10-02T13:30:00Z",
    }),
  ]);
  const { container } = view([
    "booking.appointment.read",
    "booking.appointment.manage",
  ]);

  const today = await screen.findByRole("region", { name: /^Dziś/ });
  expect(within(today).getByText("Gospodarstwo Mazur")).toBeInTheDocument();
  expect(
    within(today).getByText("Zambrów · Strzyżenie · Paweł"),
  ).toBeInTheDocument();
  expect(within(today).getByText("10:00–11:00")).toBeInTheDocument();
  expect(within(today).queryByText("Odwołana")).toBeNull();
  const tomorrow = screen.getByRole("region", { name: /^Jutro/ });
  expect(within(tomorrow).getByText("Ewa Kowalczyk")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Do przydzielenia (2)" }),
  ).toHaveAttribute("href", "/panel/calendar/queue");
  expect(api.listBookingAppointments).toHaveBeenCalledWith({
    from: "2026-10-01",
    to: "2026-10-03",
    mine: false,
  });
  expect(
    (
      await axe.run(container, {
        rules: { "color-contrast": { enabled: false } },
      })
    ).violations,
  ).toEqual([]);
});

test("everybody else sees their own day, without the queue", async () => {
  api.listBookingAppointments.mockResolvedValue([]);
  view(["booking.appointment.read"]);
  expect(await screen.findByText("Twój dzień")).toBeInTheDocument();
  expect(screen.getAllByText("Nie ma wizyt.")).toHaveLength(2);
  expect(api.listBookingAppointments).toHaveBeenCalledWith(
    expect.objectContaining({ mine: true }),
  );
  expect(api.getBookingQueue).not.toHaveBeenCalled();
});
