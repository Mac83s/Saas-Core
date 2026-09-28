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
import { TeamsPanel } from "./teams-panel";

const api = vi.hoisted(() => ({
  createTeam: vi.fn(),
  deleteTeam: vi.fn(),
  getPeopleDay: vi.fn(),
  listBookingAppointments: vi.fn(),
  listPeople: vi.fn(),
  listTeams: vi.fn(),
  updateTeam: vi.fn(),
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const SERVICE = "33333333-3333-4333-8333-333333333333";

function person(id: string, name: string, over: Record<string, unknown> = {}) {
  return {
    id,
    name,
    public_slug: id,
    membership_id: null,
    invitation_id: null,
    phone: null,
    active: true,
    service_ids: [SERVICE],
    has_hours: true,
    team_ids: [],
    public_name: null,
    created_at: "2025-03-10T12:00:00Z",
    ...over,
  };
}

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

const manager = organization([
  "booking.appointment.read",
  "booking.appointment.manage",
]);

beforeEach(() => {
  vi.clearAllMocks();
  // 10:30 in Warsaw: Marcin works, Piotr is away until tomorrow.
  vi.useFakeTimers({ toFake: ["Date"], shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-09-24T08:30:00Z"));
  api.listTeams.mockResolvedValue([
    {
      id: "t-north",
      name: "Brygada Północ",
      member_ids: ["s-marcin", "s-piotr"],
    },
  ]);
  api.listPeople.mockResolvedValue([
    person("s-marcin", "Marcin Kowalski", { membership_id: "marcin" }),
    person("s-piotr", "Piotr Wiśniewski", { membership_id: "piotr" }),
    person("s-kamil", "Kamil Duda"),
  ]);
  const works = [
    { starts_at: "2026-09-24T04:00:00Z", ends_at: "2026-09-24T14:00:00Z" },
  ];
  api.getPeopleDay.mockResolvedValue({
    date: "2026-09-24",
    timezone: "Europe/Warsaw",
    items: [
      { staff_id: "s-marcin", works, time_off: [], busy: [] },
      {
        staff_id: "s-piotr",
        works,
        time_off: [
          {
            starts_at: "2026-09-23T22:00:00Z",
            ends_at: "2026-09-25T22:00:00Z",
          },
        ],
        busy: [],
      },
    ],
  });
  api.listBookingAppointments.mockResolvedValue([
    {
      id: "visit-1",
      status: "confirmed",
      crew: [{ staff_id: "s-piotr", name: "Piotr Wiśniewski", lead: true }],
    },
    {
      id: "visit-2",
      status: "canceled",
      crew: [{ staff_id: "s-marcin", name: "Marcin Kowalski", lead: true }],
    },
  ]);
  api.createTeam.mockImplementation(async (input) => ({
    id: "t-south",
    ...input,
  }));
  api.deleteTeam.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.useRealTimers();
});

function renderPanel(current = manager, locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <TeamsPanel organization={current} />
    </NextIntlClientProvider>,
  );
}

test("zespół: członkowie, kto wolny dziś i wizyty tygodnia bez odwołanych", async () => {
  const { container } = renderPanel();
  const table = await screen.findByRole("table", { name: "Zespoły firmy" });
  const row = within(table).getByText("Brygada Północ").closest("tr")!;
  expect(
    within(row).getByText("Marcin Kowalski, Piotr Wiśniewski"),
  ).toBeInTheDocument();
  expect(
    within(row).getByText("Wolne teraz: 1 z 2 · nieobecność: Piotr Wiśniewski"),
  ).toBeInTheDocument();
  expect(within(row).getByText("1")).toBeInTheDocument();
  // This week's visits: Monday to the next Monday.
  expect(api.listBookingAppointments).toHaveBeenCalledWith({
    from: "2026-09-21",
    to: "2026-09-28",
  });
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("nowy zespół potrzebuje nazwy; usunięcie pyta i nie rusza wizyt", async () => {
  renderPanel();
  fireEvent.click(await screen.findByRole("button", { name: "Nowy zespół" }));
  const dialog = await screen.findByRole("dialog", { name: "Nowy zespół" });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz zespół" }),
  );
  expect(
    await within(dialog).findByText("Podaj nazwę zespołu."),
  ).toBeInTheDocument();
  fireEvent.change(within(dialog).getByLabelText("Nazwa"), {
    target: { value: " Brygada Południe " },
  });
  fireEvent.click(within(dialog).getByLabelText("Kamil Duda · bez konta"));
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz zespół" }),
  );
  expect(
    await screen.findByText("Utworzono zespół: Brygada Południe."),
  ).toBeInTheDocument();
  expect(api.createTeam).toHaveBeenCalledWith({
    name: "Brygada Południe",
    member_ids: ["s-kamil"],
  });

  fireEvent.click(
    await screen.findByRole("button", { name: "Więcej akcji: Brygada Północ" }),
  );
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "Usuń zespół…" }),
  );
  const confirm = await screen.findByRole("dialog", {
    name: "Usunąć zespół Brygada Północ?",
  });
  expect(
    within(confirm).getByText(/Wizyty jego członków zostają bez zmian/),
  ).toBeInTheDocument();
  fireEvent.click(within(confirm).getByRole("button", { name: "Usuń zespół" }));
  await waitFor(() => expect(api.deleteTeam).toHaveBeenCalledWith("t-north"));
  expect(
    await screen.findByText("Usunięto zespół: Brygada Północ."),
  ).toBeInTheDocument();
});

test("without managing visits the teams are read-only (EN)", async () => {
  renderPanel(organization(["booking.appointment.read"]), "en");
  expect(
    await screen.findByRole("table", { name: "The company's teams" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "New team" })).toBeNull();
  expect(
    screen.queryByRole("button", { name: /More actions: Brygada Północ/ }),
  ).toBeNull();
});
