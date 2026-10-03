import axe from "axe-core";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import type { HistoryEntry, HistoryPage } from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { HistoryPanel } from "./history-panel";

const { api } = vi.hoisted(() => ({
  api: { readOrganizationHistory: vi.fn(), readCatalogDictionary: vi.fn() },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

function entry(overrides: Partial<HistoryEntry>): HistoryEntry {
  return {
    id: crypto.randomUUID(),
    occurred_at: "2026-09-23T10:15:00Z",
    action: "organization.updated",
    actor: { name: "Ola Nowak", email: "ola@example.test" },
    channel: "panel",
    acting: null,
    target_type: "organization",
    target_id: null,
    target: null,
    changes: {},
    changed_fields: [],
    details: {},
    ...overrides,
  } as HistoryEntry;
}

function page(items: HistoryEntry[], total = items.length): HistoryPage {
  return {
    total,
    page: 1,
    page_size: 25,
    actions: [
      "organization.updated",
      "profile.updated",
      "hoofcare.visit.started",
    ],
    items,
  } as HistoryPage;
}

function view(locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <HistoryPanel />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.readCatalogDictionary.mockRejectedValue(new Error("no catalogue"));
  api.readOrganizationHistory.mockResolvedValue(
    page([
      entry({
        changes: { name: { from: "Stara nazwa", to: "Salon Uroda" } },
      }),
      entry({
        action: "profile.updated",
        actor: null,
        channel: "api_key",
        changes: {
          headline: { from: "", to: "Salon w centrum" },
          contact_phone: { changed: true },
        },
      }),
      entry({
        action: "billing.profile.updated",
        channel: null,
        changed_fields: ["legal_name", "city"],
      }),
    ]),
  );
});

test("shows who changed what, through which channel, before and after", async () => {
  const { container } = view();
  const table = await screen.findByRole("table", {
    name: "Historia zmian w organizacji, od najnowszych",
  });
  const [, rename, card, invoice] = within(table).getAllByRole("row");

  expect(within(rename).getByText("Zmieniono dane firmy")).toBeTruthy();
  expect(within(rename).getByText("Ola Nowak")).toBeTruthy();
  // The panel is the usual way and gets no badge; another way does.
  expect(within(rename).queryByText("Panel")).toBeNull();
  expect(
    within(rename).getByText("Nazwa: Stara nazwa → Salon Uroda"),
  ).toBeTruthy();

  // An integration acts without a person; a phone number keeps no value.
  expect(within(card).getAllByText("Klucz API")).toHaveLength(2);
  expect(
    within(card).getByText("Jedno zdanie o firmie: puste → Salon w centrum"),
  ).toBeTruthy();
  expect(
    within(card).getByText(
      "Telefon kontaktowy: zmieniono (dane osobowe — bez wartości)",
    ),
  ).toBeTruthy();

  // Rows from before 23.09 name their fields and carry no channel.
  expect(
    within(invoice).getByText("Zmienione pola: Nazwa do faktury, Miasto"),
  ).toBeTruthy();

  const results = await axe.run(container);
  expect(results.violations).toEqual([]);
});

test("a change the assistant made for a person says so, in both languages", async () => {
  const assistant = entry({
    acting: {
      via: "assistant",
      ref: "conversation:0199a3f0-0000-7000-8000-000000000001",
      trigger: null,
    },
  });
  api.readOrganizationHistory.mockResolvedValue(page([assistant]));
  const { unmount } = view();
  const row = within(await screen.findByRole("table")).getAllByRole("row")[1];

  expect(within(row).getByText("Ola Nowak")).toBeTruthy();
  expect(within(row).getByText("Asystent AI w imieniu osoby")).toBeTruthy();
  // The badge says how the change came, not the principal underneath.
  expect(within(row).queryByText("Panel")).toBeNull();
  unmount();

  view("en");
  expect(await screen.findByText("AI assistant on their behalf")).toBeTruthy();
});

test("the filter lists the organization's actions and asks the API again", async () => {
  view();
  const filter = await screen.findByRole("combobox");
  // A product's own action without a label still reads as words.
  expect(
    within(filter).getByRole("option", { name: "hoofcare visit started" }),
  ).toBeTruthy();

  fireEvent.change(filter, { target: { value: "profile.updated" } });

  await waitFor(() =>
    expect(api.readOrganizationHistory).toHaveBeenLastCalledWith({
      page: 1,
      pageSize: 25,
      action: "profile.updated",
    }),
  );
});

test("pages through the history on the server", async () => {
  api.readOrganizationHistory.mockResolvedValue(page([entry({})], 60));
  view("en");

  fireEvent.click(await screen.findByRole("button", { name: "Next page" }));

  await waitFor(() =>
    expect(api.readOrganizationHistory).toHaveBeenLastCalledWith({
      page: 2,
      pageSize: 25,
      action: "",
    }),
  );
  expect(
    within(screen.getByRole("table")).getByText("Company details changed"),
  ).toBeTruthy();
});

test("a failed load says so and retries", async () => {
  api.readOrganizationHistory.mockRejectedValueOnce(new Error("offline"));
  view();

  fireEvent.click(
    await screen.findByRole("button", { name: "Spróbuj ponownie" }),
  );

  const table = await screen.findByRole("table");
  expect(within(table).getByText("Zmieniono dane firmy")).toBeTruthy();
});

test("a visit's new place reads as words in both languages, without keys", async () => {
  api.readOrganizationHistory.mockResolvedValue(
    page([
      entry({
        action: "booking.appointment.place_changed",
        target_type: "appointment",
        changes: { place_town: { from: "Piątnica", to: "Zambrów" } },
      }),
    ]),
  );
  view();
  // The most frequent row of the review read as its raw key (UX plan W6).
  expect(await screen.findByText("Zmieniono miejsce wizyty")).toBeTruthy();
  expect(
    screen.getByText("Miejscowość wizyty: Piątnica → Zambrów"),
  ).toBeTruthy();
  expect(
    englishMessages.History.actions.booking_appointment_place_changed,
  ).toBe("Changed the visit's place");
});

test("the booking settings of phase 2 have their own words in the history", () => {
  // Written by booking's rules and units under their own action keys, not the
  // audit enum, so the enum's check does not see them.
  for (const action of [
    "booking_closure_changed",
    "booking_rule_changed",
    "booking_unit_blocked",
    "booking_unit_unblocked",
  ]) {
    expect(polishMessages.History.actions).toHaveProperty(action);
    expect(englishMessages.History.actions).toHaveProperty(action);
  }
});

test("a row says which object it is about, and a category by its name (UX-055)", async () => {
  api.readCatalogDictionary.mockResolvedValue({
    cities: [{ slug: "olsztyn", name: "Olsztyn", voivodeship: "" }],
    categories: [
      {
        key: "it-i-marketing",
        labels: { pl: "IT i marketing", en: "IT and marketing" },
      },
    ],
    locales: ["pl"],
  });
  api.readOrganizationHistory.mockResolvedValue(
    page([
      entry({
        action: "booking.appointment.created",
        target_type: "appointment",
        target_id: "019c5f87-fce8-739b-b960-b7a195bfc298",
        target: {
          label: "Konsultacja",
          href: "/panel/calendar?view=day&date=2026-10-03",
          at: "2026-10-03T08:00:00Z",
        },
      }),
      entry({
        action: "profile.updated",
        changes: {
          category: { from: "", to: "it-i-marketing" },
          city_slug: { from: "", to: "olsztyn" },
        },
      }),
    ]),
  );
  view();
  const visit = await screen.findByRole("link", { name: /^Konsultacja · / });
  expect(visit.getAttribute("href")).toBe(
    "/panel/calendar?view=day&date=2026-10-03",
  );
  expect(visit.closest("p")?.textContent).toMatch(
    /^Utworzono rezerwację: Konsultacja · /,
  );
  expect(await screen.findByText(/→ IT i marketing$/)).toBeTruthy();
  expect(screen.getByText(/→ Olsztyn$/)).toBeTruthy();
  expect(screen.queryByText(/it-i-marketing/)).toBeNull();
});
