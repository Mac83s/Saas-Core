import axe from "axe-core";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { FarmerToday } from "./farmer-today";

const api = vi.hoisted(() => ({
  listFarmAnimals: vi.fn(),
  listFarmShares: vi.fn(),
  listFarms: vi.fn(),
  listFollowUps: vi.fn(),
  listRegisterVisits: vi.fn(),
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const FARM = "11111111-1111-4111-8111-111111111111";
const ACCESS = { modules: [], permissions: [], isOwner: true, limited: false };

const farm = (over: Record<string, unknown> = {}) => ({
  id: FARM,
  name: "Gospodarstwo Kowalski",
  herd_number: "PL077777777-001",
  animal_count: 12,
  ...over,
});
const cow = (over: Record<string, unknown> = {}) => ({
  id: "cow",
  farm_id: FARM,
  farm_name: "Gospodarstwo Kowalski",
  national_id: "PL005432166001",
  working_number: "17",
  name: "",
  withdrawal_milk_until: null,
  withdrawal_meat_until: null,
  ...over,
});
const visit = (over: Record<string, unknown> = {}) => ({
  id: "v-1",
  status: "planned",
  scheduled_for: "2026-10-05T06:00:00Z",
  occurred_on: null,
  company_name: "Korekcja Racic Test",
  summary: "Korekcja stada",
  details: {},
  farm_id: FARM,
  farm_name: "Gospodarstwo Kowalski",
  ...over,
});

function renderToday(locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <FarmerToday access={ACCESS} firstName="Jan" />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ["Date"], shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-10-03T08:00:00Z"));
  api.listFarms.mockResolvedValue([farm()]);
  api.listFarmShares.mockResolvedValue([
    {
      status: "active",
      partner_is_company: true,
      partner_name: "Korekcja Racic Test",
    },
  ]);
  api.listFarmAnimals.mockImplementation(
    async (filters: { review?: boolean } = {}) =>
      filters.review
        ? [cow({ id: "new" })]
        : [
            cow(),
            cow({
              id: "treated",
              national_id: "PL005432166002",
              withdrawal_milk_until: "2026-10-09T00:00:00Z",
            }),
          ],
  );
  api.listRegisterVisits.mockImplementation(
    async (query: { status?: string }) =>
      query.status === "done"
        ? [
            visit({
              id: "v-done",
              status: "done",
              scheduled_for: null,
              occurred_on: "2026-09-28",
              summary: "Skorygowano 12 krów",
              details: {
                sections: [
                  {
                    title: "Krowy",
                    rows: [{ label: "PL…001", value: "LH: DD" }],
                  },
                ],
              },
            }),
          ]
        : [visit()],
  );
  api.listFollowUps.mockResolvedValue([
    {
      entry_id: "e-1",
      follow_up_on: "2026-10-12",
      occurred_on: "2026-09-28",
      summary: "Kontrola za 14 dni",
      author_organization_name: "Korekcja Racic Test",
      animal_id: "cow",
      national_id: "PL005432166001",
      working_number: "17",
      animal_name: "",
      farm_id: FARM,
      farm_name: "Gospodarstwo Kowalski",
    },
  ]);
});

afterEach(() => {
  vi.useRealTimers();
});

test("dziś rolnika: do przejrzenia, wizyty firm, kontrole, raporty i karencja", async () => {
  const { container } = renderToday();
  expect(
    await screen.findByRole("heading", { name: "Dzień dobry, Jan" }),
  ).toBeInTheDocument();
  // Done start steps do not linger: the farm is linked, numbered and stocked.
  expect(screen.queryByRole("heading", { name: "Na start" })).toBeNull();
  expect(
    screen.getByRole("heading", { name: "Do przejrzenia (1)" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Przejrzyj/ })).toHaveAttribute(
    "href",
    "/panel/animals?review=1",
  );
  expect(
    screen.getByText(
      /Korekcja Racic Test · Gospodarstwo Kowalski · Korekcja stada/,
    ),
  ).toBeInTheDocument();
  expect(screen.getByText(/PL005432166001 · 17/)).toBeInTheDocument();
  expect(screen.getByText(/mleko do/)).toBeInTheDocument();
  // No service company's start page here.
  expect(screen.queryByText(/Dodaj pierwsze gospodarstwo/)).toBeNull();
  expect((await axe.run(container)).violations).toEqual([]);

  fireEvent.click(screen.getByRole("button", { name: "Pokaż raport" }));
  const report = await screen.findByRole("dialog");
  expect(within(report).getByText("LH: DD")).toBeInTheDocument();
  expect(
    within(report).getByText("PDF tego raportu firma wysłała e-mailem."),
  ).toBeInTheDocument();
});

test("na start rolnika, dopóki gospodarstwo nie jest połączone ani opisane (EN)", async () => {
  api.listFarms.mockResolvedValue([farm({ herd_number: "", animal_count: 0 })]);
  api.listFarmShares.mockResolvedValue([]);
  api.listFarmAnimals.mockResolvedValue([]);
  api.listRegisterVisits.mockResolvedValue([]);
  api.listFollowUps.mockResolvedValue([]);
  renderToday("en");
  expect(
    await screen.findByRole("link", {
      name: "Link your farm to a company with its code",
    }),
  ).toHaveAttribute("href", "/panel/farms");
  expect(
    screen.getByRole("link", { name: "Enter the herd registration number" }),
  ).toHaveAttribute("href", `/panel/farms/${FARM}`);
  expect(screen.getByText("Nothing waits to be reviewed.")).toBeInTheDocument();
  expect(screen.getByText("No controls due.")).toBeInTheDocument();
});
