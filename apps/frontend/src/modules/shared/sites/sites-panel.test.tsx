import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import axe from "axe-core";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { ApiProblemError } from "@saas-core/api-client";
import { SitesPanel, type SitesSection } from "./sites-panel";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("#i18n/navigation", () => ({ Link: "a", useRouter: () => ({ push }) }));

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
  setPageType,
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
  setPageType: vi.fn(),
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
  setPageType,
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
const platformDomain = {
  id: "019ff20d-a000-7000-8000-000000000010",
  site_id: site.id,
  hostname: "przychodnia.core.localhost",
  kind: "platform",
  status: "verified",
  tls_status: "eligible",
  is_canonical: true,
  verification_name: "",
  verification_token: "",
  dns_cname_target: "core.localhost",
  dns_expected_ipv4: [],
  dns_expected_ipv6: [],
  dns_error_code: "",
  last_checked_at: "2026-08-12T08:00:00Z",
  last_verified_at: "2026-08-12T08:00:00Z",
  next_check_at: null,
  tls_last_requested_at: null,
  released_at: null,
  quarantine_until: null,
  created_at: "2026-08-12T08:00:00Z",
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

function renderPanel(
  props: {
    section?: SitesSection;
    pageId?: string;
    previewOnOpen?: boolean;
  } = {},
) {
  return render(
    <NextIntlClientProvider
      locale="pl"
      timeZone="Europe/Warsaw"
      messages={polishMessages}
    >
      <SitesPanel {...props} />
    </NextIntlClientProvider>,
  );
}

test("pokazuje listę site, stron i raport gotowości po polsku", async () => {
  renderPanel();

  // The section's root is the page list, titled as such under the site.
  expect(
    await screen.findByRole("heading", { level: 1, name: "Podstrony" }),
  ).not.toBeNull();
  expect(await screen.findByText("Przychodnia")).not.toBeNull();
  const list = await screen.findByRole("table", { name: "Podstrony witryny" });
  expect(await within(list).findByText("Start")).not.toBeNull();
  expect(
    screen.queryByRole("link", { name: "Otwórz opublikowaną stronę" }),
  ).toBeNull();
  // A single site means no picker: a control whose only value is what it
  // already shows is noise.
  expect(screen.queryByLabelText("Wybierz site")).toBeNull();
  cleanup();

  renderPanel({ section: "publication" });
  expect(await screen.findByText("PL: kompletne")).not.toBeNull();
  expect(screen.getByText("EN: niekompletne")).not.toBeNull();
});

test("publikuje gotowy snapshot i pokazuje potwierdzenie", async () => {
  renderPanel({ section: "publication" });

  fireEvent.click(
    await screen.findByRole("button", { name: "Opublikuj snapshot" }),
  );

  await waitFor(() => expect(publishSite).toHaveBeenCalledOnce());
  expect(publishSite.mock.calls[0]?.[0]).toBe(site.id);
  expect(await screen.findByText("Opublikowano sekwencję 1.")).not.toBeNull();
});

test("pokazuje adres opublikowanej witryny dopiero dla aktywnej publikacji", async () => {
  const customCanonicalDomain = {
    ...platformDomain,
    id: "019ff20d-a000-7000-8000-000000000011",
    hostname: "www.example.test",
    kind: "custom",
    is_canonical: true,
  };
  listSites.mockResolvedValue({
    items: [{ ...site, current_publication_id: "publication-1" }],
    next_cursor: null,
  });
  listSiteDomains.mockResolvedValue({
    items: [customCanonicalDomain, { ...platformDomain, is_canonical: false }],
  });

  render(
    <NextIntlClientProvider
      locale="pl"
      timeZone="Europe/Warsaw"
      messages={polishMessages}
    >
      <SitesPanel />
    </NextIntlClientProvider>,
  );

  const link = await screen.findByRole("link", {
    name: "Otwórz opublikowaną stronę",
  });
  expect(link).toHaveAttribute(
    "href",
    "http://przychodnia.core.localhost:3000",
  );
  expect(link).toHaveAttribute("target", "_blank");
});

test("zastępuje techniczny formularz kreatorem pierwszej strony po angielsku", async () => {
  listSites.mockResolvedValueOnce({ items: [], next_cursor: null });
  render(
    <NextIntlClientProvider
      locale="en"
      timeZone="Europe/Warsaw"
      messages={englishMessages}
    >
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
    <NextIntlClientProvider
      locale="pl"
      timeZone="Europe/Warsaw"
      messages={polishMessages}
    >
      <SitesPanel canManageBilling />
    </NextIntlClientProvider>,
  );

  const dialog = await openCreatePage();
  fireEvent.change(within(dialog).getByLabelText("Nazwa"), {
    target: { value: "Nowa podstrona" },
  });
  fireEvent.change(within(dialog).getByLabelText("Klucz podstrony"), {
    target: { value: "nowa-podstrona" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Dodaj podstronę" }),
  );

  await waitFor(() => expect(createSitePage).toHaveBeenCalledOnce());
  expect(await screen.findByText("Plan wymaga uwagi")).not.toBeNull();
  expect(
    screen.getByRole("link", { name: "Sprawdź plan i płatność" }),
  ).not.toBeNull();
  expect(
    screen.queryByRole("heading", { name: "Najpierw wybierz plan" }),
  ).toBeNull();
  // The list stays, and so does the way to add a page once the plan allows.
  expect(
    within(screen.getByRole("table", { name: "Podstrony witryny" })).getByText(
      "Start",
    ),
  ).not.toBeNull();
  expect(
    screen.getByRole("button", { name: "Dodaj podstronę" }),
  ).not.toBeNull();
});

test("przy wyczerpanym limicie podstron mówi, co zrobić", async () => {
  createSitePage.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      code: "page_limit_reached",
      detail: "Plan pozwala na 5 podstron na jednej stronie.",
      correlation_id: null,
    }),
  );
  render(
    <NextIntlClientProvider
      locale="pl"
      timeZone="Europe/Warsaw"
      messages={polishMessages}
    >
      <SitesPanel canManageBilling />
    </NextIntlClientProvider>,
  );

  const dialog = await openCreatePage();
  fireEvent.change(within(dialog).getByLabelText("Nazwa"), {
    target: { value: "Szósta podstrona" },
  });
  fireEvent.change(within(dialog).getByLabelText("Klucz podstrony"), {
    target: { value: "szosta" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Dodaj podstronę" }),
  );

  // Said in the dialog that asked, which stays open with what was typed.
  expect(
    await within(dialog).findByText(
      "Plan nie pozwala na więcej podstron na tej stronie. Usuń nieużywaną podstronę albo wybierz wyższy plan.",
    ),
  ).not.toBeNull();
});

test("wypełnia klucz podstrony z nazwy i ustępuje ręcznej zmianie", async () => {
  render(
    <NextIntlClientProvider
      locale="pl"
      timeZone="Europe/Warsaw"
      messages={polishMessages}
    >
      <SitesPanel canManageBilling />
    </NextIntlClientProvider>,
  );

  const dialog = await openCreatePage();
  const name = within(dialog).getByLabelText("Nazwa");
  const key = within(dialog).getByLabelText(
    "Klucz podstrony",
  ) as HTMLInputElement;

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
      (within(dialog).getByLabelText("Nazwa") as HTMLInputElement).value,
    ).toBe("Zupełnie inna nazwa"),
  );
  expect(key.value).toBe("kontakt");
});

test("each page of the section shows its own part, not a tab of the rest", async () => {
  const rendered = renderPanel({ section: "address" });

  expect(
    await screen.findByRole("heading", { level: 1, name: "Adres i domeny" }),
  ).not.toBeNull();
  expect(await screen.findByLabelText("Własna domena")).not.toBeNull();
  expect(screen.queryByRole("tablist")).toBeNull();
  // Publishing and the page list live at their own addresses.
  expect(
    screen.queryByRole("button", { name: "Opublikuj snapshot" }),
  ).toBeNull();
  expect(screen.queryByRole("table", { name: "Podstrony witryny" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Dodaj podstronę" })).toBeNull();

  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("kieruje właściciela bez planu do porównania oferty", async () => {
  listSites.mockRejectedValueOnce(entitlementProblem());

  render(
    <NextIntlClientProvider
      locale="pl"
      timeZone="Europe/Warsaw"
      messages={polishMessages}
    >
      <SitesPanel canManageBilling />
    </NextIntlClientProvider>,
  );

  expect(
    await screen.findByRole("heading", { name: "Najpierw wybierz plan" }),
  ).not.toBeNull();
  expect(screen.getByRole("link", { name: "Porównaj plany" })).not.toBeNull();
  expect(screen.queryByRole("button", { name: "Utwórz site" })).toBeNull();
});

async function openCreatePage() {
  expect(await screen.findByText("Przychodnia")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Dodaj podstronę" }));
  return screen.findByRole("dialog", { name: "Dodaj podstronę" });
}

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

test("the list's Edit and Preview open the page's own address", async () => {
  renderPanel();

  const list = await screen.findByRole("table", { name: "Podstrony witryny" });
  // The list is drawn before the pages arrive; act on the loaded row.
  await within(list).findByText("Start");
  fireEvent.click(within(list).getByRole("button", { name: "Edytuj" }));
  expect(push).toHaveBeenCalledWith(`/panel/sites/pages/${page.id}`);

  fireEvent.click(
    within(list).getByRole("button", { name: "Działania: Start" }),
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: "Podgląd" }));
  expect(push).toHaveBeenLastCalledWith(
    `/panel/sites/pages/${page.id}?preview=1`,
  );
});

test("the page's address opens its editor, and closing it goes back to the list", async () => {
  renderPanel({ section: "page", pageId: page.id });

  expect(
    await screen.findByRole("dialog", { name: "Edytor strony: Start" }),
  ).not.toBeNull();
  const back = screen.getByRole("button", { name: "Wróć do podstron" });
  await waitFor(() => expect(back).toBeEnabled());
  fireEvent.click(back);

  await waitFor(() => expect(push).toHaveBeenCalledWith("/panel/sites"));
});

test("a page that is gone is said to be gone, not swapped for another", async () => {
  renderPanel({
    section: "page",
    pageId: "019ff20d-a000-7000-8000-0000000000ff",
  });

  expect(
    await screen.findByText("Tej podstrony nie ma — mogła zostać usunięta."),
  ).not.toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("a new page opens in its editor", async () => {
  createSitePage.mockResolvedValueOnce({
    ...page,
    id: "019ff20d-a000-7000-8000-0000000000aa",
    name: "Cennik",
    key: "cennik",
  });
  renderPanel();
  const dialog = await openCreatePage();
  fireEvent.change(within(dialog).getByLabelText("Nazwa"), {
    target: { value: "Cennik" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Dodaj podstronę" }),
  );

  await waitFor(() =>
    expect(push).toHaveBeenCalledWith(
      "/panel/sites/pages/019ff20d-a000-7000-8000-0000000000aa",
    ),
  );
});

test("until the pages arrive the list is loading, not empty, and no page is gone", async () => {
  listSitePages.mockReturnValue(new Promise(() => {}));
  renderPanel();
  expect(await screen.findByText("Ładowanie podstron…")).not.toBeNull();
  expect(screen.queryByText("Witryna nie ma jeszcze podstron.")).toBeNull();
  cleanup();

  renderPanel({ section: "page", pageId: page.id });
  expect(await screen.findByText("Przychodnia")).not.toBeNull();
  expect(
    screen.queryByText("Tej podstrony nie ma — mogła zostać usunięta."),
  ).toBeNull();
});
