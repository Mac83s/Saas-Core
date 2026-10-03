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

import type { OrganizationSummary } from "@saas-core/api-client";

import englishMessages from "../../../../../messages/en.json";
import polishMessages from "../../../../../messages/pl.json";
import { OccupancyPanel } from "./occupancy-panel";

const api = vi.hoisted(() => ({ getBookingOccupancy: vi.fn() }));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const COTTAGES = "11111111-1111-4111-8111-111111111111";
const HALLS = "11111111-1111-4111-8111-222222222222";
const ONE = "33333333-3333-4333-8333-333333333331";
const TWO = "33333333-3333-4333-8333-333333333332";
const HALL = "33333333-3333-4333-8333-333333333333";

const organization = (permissions: string[]): OrganizationSummary => ({
  id: "019c5f87-fce8-739b-b960-b7a195bfc298",
  name: "Domki nad jeziorem",
  slug: "domki",
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

const unit = (id: string, name: string, groupId: string, group: string) => ({
  id,
  name,
  group_id: groupId,
  group_name: group,
  location_id: null,
  capacity: 6,
});

const OCCUPANCY = {
  date_from: "2026-09-24",
  date_to: "2026-10-07",
  timezone: "Europe/Warsaw",
  units: [
    unit(ONE, "Domek 1", COTTAGES, "Domki"),
    unit(TWO, "Domek 2", COTTAGES, "Domki"),
    unit(HALL, "Sala A", HALLS, "Sale"),
  ],
  held: [
    {
      unit_id: ONE,
      kind: "stay",
      // Arrives on the 26th at 16:00, leaves on the 29th at 11:00.
      starts_at: "2026-09-26T14:00:00Z",
      ends_at: "2026-09-29T09:00:00Z",
      appointment_id: "a-1",
      block_id: null,
      title: "Rodzina Nowaków",
      status: "confirmed",
    },
    {
      unit_id: TWO,
      kind: "block",
      starts_at: "2026-09-30T22:00:00Z",
      ends_at: "2026-10-02T22:00:00Z",
      appointment_id: null,
      block_id: "b-1",
      title: "Malowanie",
      status: "",
    },
  ],
  closures: [
    {
      id: "c-1",
      location_id: null,
      starts_on: "2026-10-05",
      ends_on: "2026-10-05",
      note: "",
      version: 1,
    },
  ],
};

function renderPanel(current = office, locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <OccupancyPanel organization={current} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ["Date"], shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-09-24T08:30:00Z"));
  api.getBookingOccupancy.mockResolvedValue(OCCUPANCY);
});

afterEach(() => {
  vi.useRealTimers();
});

test("obłożenie: jednostki z pobytem, blokadą i dniem zamkniętym, dwa tygodnie od dziś", async () => {
  const { container } = renderPanel();
  const grid = await screen.findByRole("group", { name: "Domek 1" });
  expect(api.getBookingOccupancy).toHaveBeenCalledWith({
    from: "2026-09-24",
    to: "2026-10-07",
  });
  const stay = within(grid).getByRole("link", {
    name: /Rodzina Nowaków, pobyt/,
  });
  expect(stay).toHaveAttribute(
    "href",
    "/panel/calendar?view=day&date=2026-09-26",
  );
  const second = screen.getByRole("group", { name: "Domek 2" });
  expect(within(second).getByText(/Blokada: Malowanie/)).toBeInTheDocument();
  expect(
    within(screen.getByRole("group", { name: "Sala A" })).getByText(
      "Wolna w tym okresie",
    ),
  ).toBeInTheDocument();
  const legend = screen.getByRole("list", { name: "Legenda" });
  for (const label of ["Potwierdzona", "Blokada", "Dzień zamknięty"])
    expect(within(legend).getByText(label)).toBeInTheDocument();
  // One unbreakable range (UX-011): the dash is glued to its dates.
  expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
    /^24 wrz\S+7 paź 2026$/,
  );
  expect((await axe.run(container)).violations).toEqual([]);
});

test("strzałki przesuwają o tydzień, a grupa zawęża jednostki", async () => {
  renderPanel();
  await screen.findByRole("group", { name: "Domek 1" });
  fireEvent.click(screen.getByRole("button", { name: "Następny tydzień" }));
  await waitFor(() =>
    expect(api.getBookingOccupancy).toHaveBeenLastCalledWith({
      from: "2026-10-01",
      to: "2026-10-14",
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Dziś" }));
  fireEvent.change(screen.getByLabelText("Grupa"), {
    target: { value: HALLS },
  });
  await waitFor(() =>
    expect(api.getBookingOccupancy).toHaveBeenLastCalledWith({
      from: "2026-09-24",
      to: "2026-10-07",
      group_id: HALLS,
    }),
  );
});

test("bez jednostek prowadzi do ustawień, a bez zarządzania nic nie wczytuje (EN)", async () => {
  api.getBookingOccupancy.mockResolvedValue({
    ...OCCUPANCY,
    units: [],
    held: [],
  });
  const { unmount } = renderPanel(office, "en");
  expect(
    await screen.findByRole("link", {
      name: "Add them in Settings › Services & schedule",
    }),
  ).toHaveAttribute("href", "/panel/settings/services");
  unmount();
  renderPanel(organization(["booking.appointment.read"]));
  expect(
    screen.getByText("Obłożenie widzi osoba, która zarządza kalendarzem."),
  ).toBeInTheDocument();
  expect(api.getBookingOccupancy).toHaveBeenCalledTimes(1);
});
