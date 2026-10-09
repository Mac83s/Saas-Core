import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import axe from "axe-core";
import { beforeEach, expect, test, vi } from "vitest";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { PanelAccessProvider } from "#components/panel/panel-access";
import type { PanelAccess } from "#lib/panel-navigation";
import { SitesPanel, type SitesSection } from "./sites-panel";

/**
 * The kept screens of „Treści platformy” in the platform's own workspace
 * (ADR-079 pkt 29, ADR-077 pkt 9): they speak of the platform's content, not
 * of a site — no line with the site's state, no site wizard — and a company's
 * same screens are what they were (`sites-panel.test.tsx`, unchanged).
 */
const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("#i18n/navigation", () => ({ Link: "a", useRouter: () => ({ push }) }));

const api = vi.hoisted(() => ({
  createSite: vi.fn(),
  getSiteOnboarding: vi.fn(),
  getSiteLocalizationReport: vi.fn(),
  listSitePages: vi.fn(),
  listSiteDomains: vi.fn(),
  listSitePublications: vi.fn(),
  listSites: vi.fn(),
}));
vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  ...api,
  getPublicLocales: vi.fn().mockRejectedValue(new Error("offline")),
}));
// The screens under the heading are tested where they live.
vi.mock("./content-types-panel", async (original) => ({
  ...(await original<typeof import("./content-types-panel")>()),
  ContentTypesPanel: () => <p>lista typów treści</p>,
  CreateContentTypeDialog: () => null,
}));
vi.mock("./translations-overview", () => ({
  TranslationsOverview: () => <p>lista tłumaczeń</p>,
  TranslateSiteAction: () => null,
}));
vi.mock("../translation/translation-tabs", () => ({
  TranslationTabs: () => null,
}));
vi.mock("./term-list-panel", () => ({
  TermListPanel: ({ address }: { address: string | null }) => (
    <p>pozycje pod adresem: {address ?? "żadnym"}</p>
  ),
  CreateCategoryDialog: () => null,
}));

const site = {
  id: "019ff20d-a000-7000-8000-000000000001",
  name: "Treści platformy",
  slug: "content",
  default_locale: "pl",
  // The builder site was published once: a company's line would say so.
  current_publication_id: "019ff20d-a000-7000-8000-000000000009",
  created_at: "2026-10-08T12:00:00Z",
  updated_at: "2026-10-08T12:00:00Z",
};

const PUBLISHER: PanelAccess = {
  modules: ["core.organizations", "shared.sites", "shared.media"],
  permissions: ["site.content.edit", "site.publish"],
  isOwner: true,
  limited: false,
  organizationType: "business",
  publisher: true,
};

function view(
  section: SitesSection,
  access: PanelAccess | null = PUBLISHER,
  locale: "pl" | "en" = "pl",
) {
  const panel = (
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <SitesPanel section={section} />
    </NextIntlClientProvider>
  );
  return render(
    access ? (
      <PanelAccessProvider access={access}>{panel}</PanelAccessProvider>
    ) : (
      panel
    ),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listSites.mockResolvedValue({ items: [site], next_cursor: null });
  api.listSitePages.mockResolvedValue({ items: [], next_cursor: null });
  api.listSiteDomains.mockResolvedValue({ items: [] });
  api.listSitePublications.mockResolvedValue({ items: [], next_cursor: null });
  api.getSiteLocalizationReport.mockResolvedValue({
    site_id: site.id,
    languages: [
      { locale: "pl", is_source: true, live: true },
      { locale: "en", is_source: false, live: false },
    ],
    pages: [],
  });
});

test("wydawca: „Treści” mówią o treściach platformy i nie pokazują stanu witryny", async () => {
  const { container } = view("content");

  expect(
    await screen.findByRole("heading", { level: 1, name: "Treści" }),
  ).toBeInTheDocument();
  expect(await screen.findByText("lista typów treści")).toBeInTheDocument();
  expect(
    screen.getByText(/^Typy treści platformy: blog i to, co dodasz obok niego/),
  ).toBeInTheDocument();
  await waitFor(() => expect(api.getSiteLocalizationReport).toHaveBeenCalled());
  // Not a site's line: no „Opublikowany”, no language „na stronie”.
  for (const word of [
    "Opublikowany",
    "Jeszcze nieopublikowana",
    "język strony",
    "na stronie",
    "Twoja witryna",
    "Otwórz opublikowaną stronę",
  ])
    expect(container, word).not.toHaveTextContent(word);

  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("wydawca: „Tłumaczenia” mówią o wpisach i nazwach, nie o podstronach, nagłówku i stopce", async () => {
  const { container } = view("translations");

  expect(
    await screen.findByRole("heading", { level: 1, name: "Tłumaczenia" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      /^Wpisy oraz nazwy typów treści, kategorii i tagów w pozostałych językach/,
    ),
  ).toBeInTheDocument();
  expect(container).not.toHaveTextContent("Podstrony");
  expect(container).not.toHaveTextContent("stopka");
});

test("wydawca: kategorie i tagi nie dostają adresu witryny, której nikt nie serwuje", async () => {
  api.listSiteDomains.mockResolvedValue({
    items: [
      {
        hostname: "serwis.core.localhost",
        kind: "platform",
        status: "verified",
        is_canonical: true,
      },
    ],
  });
  for (const section of ["contentTypeCategories", "contentTypeTags"] as const) {
    const { container, unmount } = render(
      <PanelAccessProvider access={PUBLISHER}>
        <NextIntlClientProvider
          locale="pl"
          messages={polishMessages}
          timeZone="Europe/Warsaw"
        >
          <SitesPanel section={section} typeId="type-one" />
        </NextIntlClientProvider>
      </PanelAccessProvider>,
    );
    await waitFor(() => expect(api.listSiteDomains).toHaveBeenCalled());
    expect(
      await screen.findByText("pozycje pod adresem: żadnym"),
    ).toBeInTheDocument();
    expect(container).not.toHaveTextContent("serwis.core.localhost");
    unmount();
    api.listSiteDomains.mockClear();
  }

  // A company's same screen names its site.
  render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <SitesPanel section="contentTypeCategories" typeId="type-one" />
    </NextIntlClientProvider>,
  );
  expect(
    await screen.findByText(
      /pozycje pod adresem: https?:\/\/serwis\.core\.localhost/,
    ),
  ).toBeInTheDocument();
});

test("firma: te same ekrany mają linię witryny i swoje słowa, jak dotąd", async () => {
  const { container } = view("content", null);

  expect(
    await screen.findByRole("heading", { level: 1, name: "Treści" }),
  ).toBeInTheDocument();
  expect(await screen.findByText("Opublikowany")).toBeInTheDocument();
  expect(await screen.findByText("PL · język strony")).toBeInTheDocument();
  expect(
    screen.getByText(/^Typy treści na stronie: blog i to, co dodasz obok/),
  ).toBeInTheDocument();
  expect(container).not.toHaveTextContent("Typy treści platformy");
});

test("wydawca bez rekordu strony: pytanie o język treści zamiast kreatora z subdomeną", async () => {
  api.listSites.mockResolvedValueOnce({ items: [], next_cursor: null });
  api.createSite.mockResolvedValue(site);
  const { container } = view("content");

  expect(
    await screen.findByRole("heading", { level: 2, name: "Zacznij od języka" }),
  ).toBeInTheDocument();
  // The company's wizard is not asked for, and no address is.
  expect(api.getSiteOnboarding).not.toHaveBeenCalled();
  expect(container).not.toHaveTextContent(/subdomen|adres strony/i);
  expect(
    [...container.querySelectorAll("input, select")].map((field) => field.id),
  ).toEqual(["publisher-start-language"]);
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);

  fireEvent.change(screen.getByLabelText("Język treści"), {
    target: { value: "en" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zacznij pisać" }));

  await waitFor(() => expect(api.createSite).toHaveBeenCalledTimes(1));
  const [input, key] = api.createSite.mock.calls[0]!;
  // A name nobody reads, the language the content depends on — and no
  // subdomain: the record's platform address is the API's to make up.
  expect(input).toEqual({
    name: "Treści platformy",
    slug: "content",
    default_locale: "en",
  });
  expect(key).toMatch(/^publisher-start-/);
  // The sites are asked for again, and the list of types takes over.
  expect(await screen.findByText("lista typów treści")).toBeInTheDocument();
});

test("a company without a site still gets its wizard, in English too", async () => {
  api.listSites.mockResolvedValueOnce({ items: [], next_cursor: null });
  api.getSiteOnboarding.mockResolvedValue({
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
  view("content", null, "en");

  await waitFor(() => expect(api.getSiteOnboarding).toHaveBeenCalled());
  expect(
    screen.queryByRole("heading", { name: "Start with the language" }),
  ).not.toBeInTheDocument();
  expect(api.createSite).not.toHaveBeenCalled();
});

test("a publisher's failed start says why and can be tried again", async () => {
  api.listSites.mockResolvedValueOnce({ items: [], next_cursor: null });
  api.createSite.mockRejectedValueOnce(new Error("offline"));
  view("content", PUBLISHER, "en");

  fireEvent.click(await screen.findByRole("button", { name: "Start writing" }));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Start writing" })).toBeEnabled();
});
