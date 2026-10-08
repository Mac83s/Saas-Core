import { render, screen } from "@testing-library/react";
import { createTranslator, NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import type { OrganizationSummary } from "@saas-core/api-client";

import polishMessages from "../../../../messages/pl.json";

const { server } = vi.hoisted(() => ({
  server: { organization: null as unknown },
}));
vi.mock("#lib/server-auth", () => ({
  getServerUser: async () => ({
    email: "anna@saas.test",
    first_name: "Anna",
    operator_level: 0,
  }),
  getServerCurrentOrganization: async () => server.organization,
}));
vi.mock("#lib/panel-messages", () => ({
  getPanelTranslations: async (namespace: string) =>
    createTranslator({
      locale: "pl",
      messages: polishMessages as never,
      namespace: namespace as never,
    }),
}));
vi.mock("next-intl/server", () => ({ getLocale: async () => "pl" }));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));
vi.mock("#i18n/navigation", () => ({ Link: "a", usePathname: () => "/panel" }));
// The three parts of the start, each tested where it lives.
vi.mock("../../../modules/shared/booking", () => ({
  DayAgenda: () => <p>agenda dnia</p>,
}));
vi.mock("#components/panel/getting-started", () => ({
  GettingStarted: () => <p>lista na start</p>,
}));
vi.mock("#components/panel/site-state", () => ({
  SiteState: () => <p>stan strony</p>,
}));
// A company's type with the site builder, the calendar and a subscription.
vi.mock("#lib/organization-types", async (original) => ({
  ...(await original<typeof import("#lib/organization-types")>()),
  modulesFor: () =>
    new Set([
      "core.identity",
      "core.organizations",
      "shared.billing",
      "shared.sites",
      "shared.booking",
      "shared.translation",
    ]),
  typeRole: () => null,
}));

const { default: PanelHomePage } = await import("./page");

const OWNER = [
  "organization.read",
  "organization.members.manage",
  "booking.appointment.read",
  "booking.appointment.manage",
  "site.content.edit",
];

function organization(kind: string, permissions = OWNER): OrganizationSummary {
  return {
    id: "019f0000-0000-7000-8000-000000000001",
    name: "Serwis",
    slug: "serwis",
    workspace_kind: kind,
    organization_type: "business",
    status: "active",
    default_locale: "pl",
    timezone: "Europe/Warsaw",
    currency: "PLN",
    version: 1,
    membership_status: "active",
    role: "owner",
    permissions,
    active: true,
  };
}

async function view() {
  return render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      {await PanelHomePage()}
    </NextIntlClientProvider>,
  );
}

const tiles = () =>
  screen
    .getAllByRole("link")
    .map((link) => [
      link.getAttribute("href"),
      link.querySelector("span.block")?.textContent,
    ]);

beforeEach(() => {
  server.organization = null;
});

test("wydawca: stan strony i części strony pod nazwami z menu — bez dnia, „Na start”, planu i zespołu", async () => {
  server.organization = organization("platform");
  await view();

  expect(
    screen.getByRole("heading", { level: 1, name: "Dzień dobry, Anna" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Stan Twojej strony, a pod nim skróty do jej części."),
  ).toBeInTheDocument();
  expect(screen.getByText("stan strony")).toBeInTheDocument();
  expect(screen.queryByText("agenda dnia")).not.toBeInTheDocument();
  expect(screen.queryByText("lista na start")).not.toBeInTheDocument();
  expect(tiles()).toEqual([
    ["/panel/sites", "Podstrony"],
    // „Treści”: the workspace runs content types whatever companies are
    // offered (ADR-079 pkt 28).
    ["/panel/sites/content", "Treści"],
    ["/panel/sites/translations", "Tłumaczenia"],
    ["/panel/sites/address", "Adres i domeny"],
  ]);
});

test("wydawca bez prawa do treści strony nie dostaje ani stanu strony, ani skrótów", async () => {
  server.organization = organization("platform", ["organization.read"]);
  await view();

  expect(screen.queryByText("stan strony")).not.toBeInTheDocument();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { level: 2, name: "Co chcesz zrobić?" }),
  ).not.toBeInTheDocument();
});

test("firma: dzień, „Na start” i skróty firmy jak dotąd", async () => {
  server.organization = organization("business");
  await view();

  expect(
    screen.getByText("Twój dzień, a pod nim to, co zostało do ustawienia."),
  ).toBeInTheDocument();
  expect(screen.getByText("agenda dnia")).toBeInTheDocument();
  expect(screen.getByText("lista na start")).toBeInTheDocument();
  expect(screen.queryByText("stan strony")).not.toBeInTheDocument();
  expect(tiles()).toEqual([
    ["/panel/sites", "Strona internetowa"],
    ["/panel/calendar", "Kalendarz"],
    ["/panel/team", "Zespół"],
    ["/panel/settings/billing", "Plan i płatności"],
  ]);
});
