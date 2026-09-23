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
  api: { readOrganizationHistory: vi.fn() },
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
    target_type: "organization",
    target_id: null,
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
  expect(within(rename).getByText("Panel")).toBeTruthy();
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
