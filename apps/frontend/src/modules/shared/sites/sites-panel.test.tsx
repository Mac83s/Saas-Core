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
import { SitesPanel } from "./sites-panel";

const {
  createSite,
  createSitePage,
  getSiteLocalizationReport,
  listSitePages,
  listSites,
  publishSite,
} = vi.hoisted(() => ({
  createSite: vi.fn(),
  createSitePage: vi.fn(),
  getSiteLocalizationReport: vi.fn(),
  listSitePages: vi.fn(),
  listSites: vi.fn(),
  publishSite: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  createSite,
  createSitePage,
  getSiteLocalizationReport,
  listSitePages,
  listSites,
  publishSite,
}));

const site = {
  id: "019ff20d-a000-7000-8000-000000000001",
  name: "Przychodnia",
  slug: "przychodnia",
  default_locale: "pl",
  current_publication_id: null,
  created_at: "2026-08-11T12:00:00Z",
  updated_at: "2026-08-11T12:00:00Z",
};
const page = {
  id: "019ff20d-a000-7000-8000-000000000002",
  site_id: site.id,
  name: "Start",
  key: "home",
  version: 1,
  current_draft_id: "019ff20d-a000-7000-8000-000000000003",
  current_draft_hash: "a".repeat(64),
  created_at: "2026-08-11T12:00:00Z",
  updated_at: "2026-08-11T12:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  listSites.mockResolvedValue({ items: [site], next_cursor: null });
  listSitePages.mockResolvedValue({ items: [page], next_cursor: null });
  getSiteLocalizationReport.mockResolvedValue({
    site_id: site.id,
    default_locale: "pl",
    supported_locales: ["pl", "en"],
    ready_to_publish: true,
    pages: [
      {
        page_id: page.id,
        page_key: page.key,
        page_name: page.name,
        locales: [
          {
            locale: "pl",
            translation_id: "019ff20d-a000-7000-8000-000000000004",
            version: 1,
            slug: "start",
            path: "/start/",
            canonical_path: "/start/",
            title: "Start",
            description: "Opis",
            social_title: "Start",
            social_description: "Opis",
            fallback_fields: [],
            missing_fields: [],
            complete: true,
            slug_locked: false,
          },
          {
            locale: "en",
            translation_id: null,
            version: null,
            slug: null,
            path: null,
            canonical_path: null,
            title: null,
            description: null,
            social_title: null,
            social_description: null,
            fallback_fields: [],
            missing_fields: ["slug"],
            complete: false,
            slug_locked: false,
          },
        ],
        hreflang: { pl: "/start/" },
        x_default: "/start/",
      },
    ],
  });
  publishSite.mockResolvedValue({
    id: "019ff20d-a000-7000-8000-000000000005",
    site_id: site.id,
    sequence: 1,
    snapshot_schema_version: 1,
    snapshot_hash: "b".repeat(64),
    created_at: "2026-08-11T12:01:00Z",
  });
});

afterEach(cleanup);

test("pokazuje listę site, stron i raport gotowości po polsku", async () => {
  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <SitesPanel />
    </NextIntlClientProvider>,
  );

  expect(
    await screen.findByRole("heading", { name: "Treść strony" }),
  ).not.toBeNull();
  expect(await screen.findByText("Przychodnia")).not.toBeNull();
  expect(await screen.findByText("Start")).not.toBeNull();
  expect(screen.getByText("PL: kompletne")).not.toBeNull();
  expect(screen.getByText("EN: niekompletne")).not.toBeNull();
  expect(screen.getByLabelText("Wybierz site")).not.toBeNull();
  expect(screen.getByLabelText("Wybierz podstronę")).not.toBeNull();
});

test("publikuje gotowy snapshot i pokazuje potwierdzenie", async () => {
  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <SitesPanel />
    </NextIntlClientProvider>,
  );

  const button = await screen.findByRole("button", {
    name: "Opublikuj snapshot",
  });
  fireEvent.click(button);

  await waitFor(() => expect(publishSite).toHaveBeenCalledOnce());
  expect(publishSite.mock.calls[0]?.[0]).toBe(site.id);
  expect(await screen.findByText("Opublikowano sekwencję 1.")).not.toBeNull();
});

test("renderuje pusty stan i formularze po angielsku", async () => {
  listSites.mockResolvedValueOnce({ items: [], next_cursor: null });
  render(
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      <SitesPanel />
    </NextIntlClientProvider>,
  );

  expect(
    await screen.findByRole("heading", { name: "Site content" }),
  ).not.toBeNull();
  expect(screen.getByRole("button", { name: "Create site" })).not.toBeNull();
  expect(screen.getByRole("button", { name: "Add page" })).not.toBeNull();
  expect(
    screen.getByText("Choose a site to load its readiness report."),
  ).not.toBeNull();
});
