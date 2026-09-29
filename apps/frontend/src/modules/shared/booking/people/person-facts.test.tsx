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
import { PerformancePanel } from "./performance-panel";
import { PersonHistory, PersonResults, periodDays } from "./person-facts";

const api = vi.hoisted(() => ({
  getStaffFacts: vi.fn(),
  getStaffHistory: vi.fn(),
  getTeamPerformance: vi.fn(),
  listTeams: vi.fn(),
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const MARCIN = "0199c5f8-0000-7000-8000-000000000011";
const PIOTR = "0199c5f8-0000-7000-8000-000000000012";
const NORTH = "0199c5f8-0000-7000-8000-000000000021";

const facts = {
  period_from: "2026-09-01",
  period_to: "2026-09-24",
  previous_from: "2026-08-08",
  previous_to: "2026-08-31",
  groups: [
    {
      provider: "calendar",
      metrics: [
        {
          key: "visits_done",
          value: 19,
          unit: "count",
          parts: { lead: 11, crew: 8 },
          previous: 17,
        },
        {
          key: "hours",
          value: 5280,
          unit: "minutes",
          parts: {},
          previous: 4740,
        },
      ],
    },
    {
      provider: "inventory",
      metrics: [
        { key: "used", value: 186840, unit: "money", parts: {}, previous: 0 },
        {
          key: "on_hand",
          value: 17560,
          unit: "money",
          parts: {},
          previous: null,
        },
      ],
    },
    {
      // A product's own numbers, named by the product's messages or its words.
      provider: "hoofcare",
      metrics: [
        { key: "cows", value: 1126, unit: "count", parts: {}, previous: 1004 },
      ],
    },
  ],
};

const organization = {
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
  role: "owner",
  permissions: ["booking.staff.performance.read"],
  active: true,
} as OrganizationSummary;

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ["Date"], shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-09-24T08:30:00Z"));
  api.getStaffFacts.mockResolvedValue(facts);
  api.getStaffHistory.mockResolvedValue({
    period_from: "2026-09-01",
    period_to: "2026-09-24",
    kinds: ["calendar", "inventory", "account"],
    items: [
      {
        at: "2026-09-24T10:05:00Z",
        kind: "calendar",
        event: "visit_done",
        params: {
          customer: "Gospodarstwo Kaczmarków",
          service: "Korekcja",
          role: "lead",
        },
        value: null,
        unit: "",
      },
      {
        at: "2026-09-24T09:40:00Z",
        kind: "inventory",
        event: "used",
        params: {
          number: "RW/2026/09/311",
          lines: [{ name: "Klocek", quantity: "6", unit: "piece" }],
        },
        value: 16940,
        unit: "money",
      },
    ],
    next_before: "2026-09-24T09:40:00Z",
  });
  api.listTeams.mockResolvedValue([
    {
      id: NORTH,
      name: "Brygada Północ",
      member_ids: [MARCIN, PIOTR],
      created_at: "",
    },
  ]);
  api.getTeamPerformance.mockResolvedValue({
    period_from: "2026-09-01",
    period_to: "2026-09-24",
    columns: [
      {
        provider: "calendar",
        metrics: [
          { key: "visits_done", unit: "count" },
          { key: "hours", unit: "minutes" },
        ],
      },
      { provider: "inventory", metrics: [{ key: "used", unit: "money" }] },
    ],
    items: [
      {
        staff_id: MARCIN,
        name: "Marcin Kowalski",
        membership_id: "m1",
        team_ids: [NORTH],
        groups: {
          calendar: { visits_done: 19, hours: 5280 },
          inventory: { used: 186840 },
        },
      },
      {
        staff_id: PIOTR,
        name: "Krzysztof Nowak",
        membership_id: null,
        team_ids: [],
        groups: { calendar: { visits_done: 9, hours: 2400 } },
      },
    ],
  });
});

const denied = () =>
  new ApiProblemError({
    type: "about:blank",
    title: "Forbidden",
    status: 403,
    code: "organization_permission_denied",
    detail: null,
    correlation_id: null,
  });

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function renderIn(node: React.ReactNode, locale: "en" | "pl" = "en") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "en" ? englishMessages : polishMessages}
      timeZone="Europe/Warsaw"
    >
      {node}
    </NextIntlClientProvider>,
  );
}

test("periods are the organization's days", () => {
  const now = new Date("2026-09-24T08:30:00Z");
  expect(periodDays("month", now, "Europe/Warsaw")).toEqual({
    from: "2026-09-01",
    to: "2026-09-24",
  });
  expect(periodDays("previous", now, "Europe/Warsaw")).toEqual({
    from: "2026-08-01",
    to: "2026-08-31",
  });
  expect(periodDays("quarter", now, "Europe/Warsaw")).toEqual({
    from: "2026-06-27",
    to: "2026-09-24",
  });
  expect(periodDays("year", now, "Europe/Warsaw")).toEqual({
    from: "2026-01-01",
    to: "2026-09-24",
  });
});

test.each([
  ["pl", polishMessages],
  ["en", englishMessages],
] as const)(
  "the results read each module's numbers in %s",
  async (locale, messages) => {
    const rendered = renderIn(
      <PersonResults currency="PLN" staffId={MARCIN} zone="Europe/Warsaw" />,
      locale,
    );
    expect(
      await screen.findByRole("heading", {
        name: messages.StaffFacts.provider.calendar,
      }),
    ).not.toBeNull();
    expect(
      screen.getByText(messages.StaffFacts.metric.inventory.used),
    ).not.toBeNull();
    // The product's number has no core word: its key reads as words.
    expect(screen.getByText("Cows")).not.toBeNull();
    expect((await axe.run(rendered.container)).violations).toHaveLength(0);
  },
);

test("a number stands beside the period before it; today's stock stands alone", async () => {
  renderIn(
    <PersonResults currency="PLN" staffId={MARCIN} zone="Europe/Warsaw" />,
  );
  const visits = (await screen.findByText("Visits done")).parentElement!;
  expect(within(visits).getByText("19")).not.toBeNull();
  expect(
    within(visits).getByText("11 as the lead · 8 in the crew"),
  ).not.toBeNull();
  expect(within(visits).getByText("previous period: 17")).not.toBeNull();
  expect(
    within(screen.getByText("Hours on visits").parentElement!).getByText(
      "88 h",
    ),
  ).not.toBeNull();
  const stock = screen.getByText("On hand").parentElement!;
  expect(within(stock).queryByText(/previous period/)).toBeNull();
  expect(api.getStaffFacts).toHaveBeenCalledWith(MARCIN, {
    from: "2026-09-01",
    to: "2026-09-24",
  });

  fireEvent.change(screen.getByLabelText("Period"), {
    target: { value: "previous" },
  });
  await waitFor(() =>
    expect(api.getStaffFacts).toHaveBeenLastCalledWith(MARCIN, {
      from: "2026-08-01",
      to: "2026-08-31",
    }),
  );
});

test("somebody else's results the API refuses show nothing, not an error", async () => {
  api.getStaffFacts.mockRejectedValue(denied());
  const { container } = renderIn(
    <PersonResults currency="PLN" staffId={PIOTR} zone="Europe/Warsaw" />,
  );
  await waitFor(() => expect(container.textContent).toBe(""));
});

test("the history tells each event in words and loads older ones", async () => {
  renderIn(
    <PersonHistory currency="PLN" staffId={MARCIN} zone="Europe/Warsaw" />,
  );
  expect(await screen.findByText("Visit done")).not.toBeNull();
  expect(
    screen.getByText("Gospodarstwo Kaczmarków · Korekcja · as the lead"),
  ).not.toBeNull();
  expect(screen.getByText("RW/2026/09/311 · 6× Klocek")).not.toBeNull();
  fireEvent.change(screen.getByLabelText("Kind"), {
    target: { value: "inventory" },
  });
  await waitFor(() =>
    expect(api.getStaffHistory).toHaveBeenLastCalledWith(MARCIN, {
      from: "2026-09-01",
      to: "2026-09-24",
      kind: "inventory",
    }),
  );
  fireEvent.click(await screen.findByRole("button", { name: "Load older" }));
  await waitFor(() =>
    expect(api.getStaffHistory).toHaveBeenLastCalledWith(MARCIN, {
      from: "2026-09-01",
      to: "2026-09-24",
      kind: "inventory",
      before: "2026-09-24T09:40:00Z",
    }),
  );
});

test("performance puts everybody's numbers side by side, and nothing is not zero", async () => {
  const rendered = renderIn(<PerformancePanel organization={organization} />);
  expect(await screen.findByText("Marcin Kowalski")).not.toBeNull();
  expect(screen.getAllByText("88 h").length).toBeGreaterThan(0);
  // No account, no stock: the warehouse has nothing on Krzysztof.
  expect(screen.getAllByText("no data").length).toBeGreaterThan(0);
  expect(screen.getByText("How we count")).not.toBeNull();
  fireEvent.change(screen.getByLabelText("Team"), { target: { value: NORTH } });
  await waitFor(() =>
    expect(api.getTeamPerformance).toHaveBeenLastCalledWith({
      from: "2026-09-01",
      to: "2026-09-24",
      team: NORTH,
    }),
  );
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("performance without the right says so instead of an empty table", async () => {
  api.getTeamPerformance.mockRejectedValue(denied());
  renderIn(<PerformancePanel organization={organization} />);
  expect(
    await screen.findByText(
      "Other people's results are for the owner and the administrator.",
    ),
  ).not.toBeNull();
});
