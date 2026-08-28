import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import axe from "axe-core";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { ApiProblemError } from "@saas-core/api-client";
import { SitesPanel } from "./sites-panel";

vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const {
  createSitePage,
  getPageDraft,
  getSiteOnboarding,
  getSiteLocalizationReport,
  listMediaAssets,
  listPageTranslations,
  listSitePages,
  listSiteDomains,
  listSitePublications,
  listSites,
  publishSite,
} = vi.hoisted(() => ({
  createSitePage: vi.fn(),
  getPageDraft: vi.fn(),
  getSiteOnboarding: vi.fn(),
  getSiteLocalizationReport: vi.fn(),
  listMediaAssets: vi.fn(),
  listPageTranslations: vi.fn(),
  listSitePages: vi.fn(),
  listSiteDomains: vi.fn(),
  listSitePublications: vi.fn(),
  listSites: vi.fn(),
  publishSite: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  createSitePage,
  getPageDraft,
  getSiteOnboarding,
  getSiteLocalizationReport,
  listMediaAssets,
  listPageTranslations,
  listSitePages,
  listSiteDomains,
  listSitePublications,
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
  page_type: "landing",
  automation_policy: "manual",
  draft_author: null,
  created_at: "2026-08-11T12:00:00Z",
  updated_at: "2026-08-11T12:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  listSites.mockResolvedValue({ items: [site], next_cursor: null });
  getSiteOnboarding.mockResolvedValue({
    id: null,
    version: 0,
    step: "address",
    name: "",
    subdomain_label: "",
    default_locale: "pl",
    platform_domain: "sites.example.test",
    hostname: "",
    site_id: null,
    updated_at: null,
  });
  listSitePages.mockResolvedValue({ items: [page], next_cursor: null });
  listSiteDomains.mockResolvedValue({ items: [] });
  listSitePublications.mockResolvedValue({ items: [], next_cursor: null });
  getPageDraft.mockResolvedValue({
    page_id: page.id,
    version: 0,
    draft_id: null,
    content_hash: null,
    created_at: null,
    blocks: [],
    media_asset_ids: [],
  });
  listPageTranslations.mockResolvedValue({
    page_id: page.id,
    default_locale: "pl",
    supported_locales: ["pl", "en"],
    items: [],
  });
  listMediaAssets.mockResolvedValue({ items: [], next_cursor: null });
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
    await screen.findByRole("heading", { name: "Twoja witryna" }),
  ).not.toBeNull();
  expect(await screen.findByText("Przychodnia")).not.toBeNull();
  // The pages mode is the default, so its picker is on screen without a click.
  expect(await screen.findByLabelText("Wybierz podstronę")).not.toBeNull();
  // The selected page shows as the picker's value, not as loose text.
  expect(await screen.findByDisplayValue("Start")).not.toBeNull();
  // A single site means no picker: a control whose only value is what it
  // already shows is noise.
  expect(screen.queryByLabelText("Wybierz site")).toBeNull();

  fireEvent.click(screen.getByRole("tab", { name: "Publikacja" }));
  expect(await screen.findByText("PL: kompletne")).not.toBeNull();
  expect(screen.getByText("EN: niekompletne")).not.toBeNull();
});

test("publikuje gotowy snapshot i pokazuje potwierdzenie", async () => {
  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <SitesPanel />
    </NextIntlClientProvider>,
  );

  fireEvent.click(await screen.findByRole("tab", { name: "Publikacja" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Opublikuj snapshot" }),
  );

  await waitFor(() => expect(publishSite).toHaveBeenCalledOnce());
  expect(publishSite.mock.calls[0]?.[0]).toBe(site.id);
  expect(await screen.findByText("Opublikowano sekwencję 1.")).not.toBeNull();
});

test("zastępuje techniczny formularz kreatorem pierwszej strony po angielsku", async () => {
  listSites.mockResolvedValueOnce({ items: [], next_cursor: null });
  render(
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      <SitesPanel />
    </NextIntlClientProvider>,
  );

  expect(
    await screen.findByRole("heading", { name: "Your website" }),
  ).not.toBeNull();
  expect(
    await screen.findByRole("heading", { name: "Choose your website address" }),
  ).not.toBeNull();
  expect(screen.getByLabelText("Preferred address")).not.toBeNull();
  expect(screen.queryByText("Slug")).toBeNull();
  expect(screen.queryByRole("button", { name: "Create site" })).toBeNull();
});

test("po odrzuceniu mutacji zachowuje treść i kieruje do płatności", async () => {
  createSitePage.mockRejectedValueOnce(entitlementProblem());
  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <SitesPanel canManageBilling />
    </NextIntlClientProvider>,
  );

  expect(await screen.findByText("Przychodnia")).not.toBeNull();
  fireEvent.change(
    screen.getByLabelText("Nazwa", { selector: "input#page-name" }),
    { target: { value: "Nowa podstrona" } },
  );
  fireEvent.change(
    screen.getByLabelText("Klucz podstrony", { selector: "input#page-key" }),
    { target: { value: "nowa-podstrona" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Dodaj podstronę" }));

  await waitFor(() => expect(createSitePage).toHaveBeenCalledOnce());
  expect(await screen.findByText("Plan wymaga uwagi")).not.toBeNull();
  expect(
    screen.getByRole("link", { name: "Sprawdź plan i płatność" }),
  ).not.toBeNull();
  expect(
    screen.queryByRole("heading", { name: "Najpierw wybierz plan" }),
  ).toBeNull();
  // The selected page shows as the picker's value, not as loose text.
  expect(await screen.findByDisplayValue("Start")).not.toBeNull();
  expect(
    screen.getByRole("button", { name: "Dodaj podstronę" }),
  ).not.toBeNull();
});

test("wypełnia klucz podstrony z nazwy i ustępuje ręcznej zmianie", async () => {
  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <SitesPanel canManageBilling />
    </NextIntlClientProvider>,
  );

  expect(await screen.findByText("Przychodnia")).not.toBeNull();
  const name = screen.getByLabelText("Nazwa", { selector: "input#page-name" });
  const key = screen.getByLabelText("Klucz podstrony", {
    selector: "input#page-key",
  }) as HTMLInputElement;

  // ł has no decomposition, so a naive slug would drop it entirely.
  fireEvent.change(name, { target: { value: "Gabinet Łukasza" } });
  await waitFor(() => expect(key.value).toBe("gabinet-lukasza"));

  fireEvent.change(name, { target: { value: "O nas" } });
  await waitFor(() => expect(key.value).toBe("o-nas"));

  // Once edited by hand the key is the operator's; it must stop rewriting
  // itself under them.
  fireEvent.change(key, { target: { value: "kontakt" } });
  fireEvent.change(name, { target: { value: "Zupełnie inna nazwa" } });
  await waitFor(() =>
    expect(
      (
        screen.getByLabelText("Nazwa", {
          selector: "input#page-name",
        }) as HTMLInputElement
      ).value,
    ).toBe("Zupełnie inna nazwa"),
  );
  expect(key.value).toBe("kontakt");
});

test("rozdziela zadania na tryby zamiast jednego długiego widoku", async () => {
  const rendered = render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <SitesPanel />
    </NextIntlClientProvider>,
  );

  expect(await screen.findByRole("tablist")).not.toBeNull();
  const modes = screen
    .getAllByRole("tab")
    .map((tab) => tab.textContent?.trim());
  expect(modes).toEqual(["Podstrony", "Treść", "Blog", "Publikacja", "Adres"]);

  // Publishing and the address are done once, so they must not sit on the
  // screen used for daily editing.
  expect(
    screen.queryByRole("button", { name: "Opublikuj snapshot" }),
  ).toBeNull();
  expect(screen.queryByLabelText("Własna domena")).toBeNull();

  fireEvent.click(screen.getByRole("tab", { name: "Adres" }));
  expect(await screen.findByLabelText("Własna domena")).not.toBeNull();
  expect(
    screen.queryByRole("button", { name: "Opublikuj snapshot" }),
  ).toBeNull();

  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("kieruje właściciela bez planu do porównania oferty", async () => {
  listSites.mockRejectedValueOnce(entitlementProblem());

  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <SitesPanel canManageBilling />
    </NextIntlClientProvider>,
  );

  expect(
    await screen.findByRole("heading", { name: "Najpierw wybierz plan" }),
  ).not.toBeNull();
  expect(screen.getByRole("link", { name: "Porównaj plany" })).not.toBeNull();
  expect(screen.queryByRole("button", { name: "Utwórz site" })).toBeNull();
});

function entitlementProblem() {
  return new ApiProblemError({
    type: "about:blank",
    title: "Forbidden",
    status: 403,
    code: "entitlement_required",
    detail: "Plan organizacji nie pozwala na tę operację.",
    correlation_id: null,
  });
}
