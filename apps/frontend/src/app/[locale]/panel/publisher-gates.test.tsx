import { beforeEach, expect, test, vi } from "vitest";

import type { OrganizationSummary } from "@saas-core/api-client";

/**
 * What the API refuses a platform workspace whatever the role — invitations
 * and a plan (ADR-077 pkt 2) — and a module outside its list (pkt 9), the
 * panel does not open there either: the pages answer „Nie ma takiej strony”.
 * So do the site builder's screens (ADR-079 pkt 29) — pages and their
 * editor, the menu, the site's publication, its address, the enquiries its
 * forms bring — though the API behind them stays open: no host serves the
 * workspace's builder site. A company's pages are drawn.
 */
const { server } = vi.hoisted(() => ({
  server: { organization: null as unknown },
}));
class NotFound extends Error {}
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new NotFound();
  },
}));
vi.mock("#lib/server-auth", () => ({
  getServerCurrentOrganization: async () => server.organization,
  getServerSettingsSchema: async () => ({ areas: [], groups: [] }),
}));
vi.mock("#lib/panel-messages", () => ({
  getPanelTranslations: async () => (key: string) => key,
}));
vi.mock("next-intl/server", () => ({ getLocale: async () => "pl" }));
// The screens themselves are tested where they live.
vi.mock("../../../modules/shared/billing", () => ({
  CreditsPanel: () => null,
  CustomerBillingPanel: () => null,
}));
vi.mock("../../../modules/shared/seo", () => ({ SeoAuditsPanel: () => null }));
vi.mock("../../../modules/core/organizations", () => ({
  SettingsGroupForm: () => null,
}));
vi.mock("../../../marketing/content", () => ({
  productCopy: () => ({ pricing: { features: {} } }),
}));
vi.mock("#components/panel/panel-page", () => ({ PanelPage: () => null }));
vi.mock("../../../modules/shared/sites", () => ({ SitesPanel: () => null }));
vi.mock("../../../modules/shared/notifications", () => ({
  NotificationsPanel: () => null,
}));
vi.mock("#lib/organization-types", async (original) => ({
  ...(await original<typeof import("#lib/organization-types")>()),
  modulesFor: () =>
    new Set([
      "core.organizations",
      "shared.billing",
      "shared.seo",
      "shared.sites",
    ]),
  typeRole: () => null,
}));

const { default: TeamLayout } = await import("./team/layout");
const { default: CalendarLayout } = await import("./calendar/layout");
const { default: BillingPage } = await import("./settings/billing/page");
const { default: CreditsPage } = await import("./settings/credits/page");
const { default: SeoPage } = await import("./seo/page");
const { default: SitePagesPage } = await import("./sites/page");
const { default: SitePageEditorPage } =
  await import("./sites/pages/[pageId]/page");
const { default: SiteMenuPage } = await import("./sites/menu/page");
const { default: SitePublicationPage } =
  await import("./sites/publication/page");
const { default: SiteAddressPage } = await import("./sites/address/page");
const { default: InquiriesPage } = await import("./notifications/page");
const { default: ContentPage } = await import("./sites/content/page");
const { default: TranslationsPage } = await import("./sites/translations/page");
const { default: SiteIntegrationsPage } =
  await import("./sites/integrations/page");

function organization(kind: string): OrganizationSummary {
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
    permissions: [
      "organization.members.read",
      "organization.billing.manage",
      "site.content.edit",
    ],
    active: true,
  };
}

const pages = {
  Zespół: () => TeamLayout({ children: "strona zespołu" }),
  Kalendarz: () => CalendarLayout({ children: "strona kalendarza" }),
  "Plan i płatności": () => BillingPage(),
  Kredyty: () => CreditsPage(),
  "Widoczność w Google": () => SeoPage(),
  // The site builder's screens (ADR-079 pkt 29).
  Podstrony: () => SitePagesPage(),
  "Edytor podstrony": () =>
    SitePageEditorPage({
      params: Promise.resolve({ pageId: "page-one" }),
      searchParams: Promise.resolve({}),
    }),
  Menu: () => SiteMenuPage(),
  Publikacja: () => SitePublicationPage(),
  "Adres i domeny": () => SiteAddressPage(),
  "Zapytania ze strony": () => InquiriesPage(),
};

// What a publisher keeps of „Strona internetowa”: both panels draw them.
const kept = {
  Treści: () => ContentPage(),
  Tłumaczenia: () => TranslationsPage(),
  Integracje: () => SiteIntegrationsPage(),
};

beforeEach(() => {
  server.organization = null;
});

test.each(Object.keys(pages) as (keyof typeof pages)[])(
  "„%s”: w workspace platformy nie ma takiej strony, w firmie jest",
  async (name) => {
    server.organization = organization("platform");
    await expect(pages[name]()).rejects.toBeInstanceOf(NotFound);

    server.organization = organization("business");
    await expect(pages[name]()).resolves.toBeTruthy();
  },
);

test.each(Object.keys(kept) as (keyof typeof kept)[])(
  "„%s”: zostaje wydawcy i firmie",
  async (name) => {
    server.organization = organization("platform");
    await expect(kept[name]()).resolves.toBeTruthy();

    server.organization = organization("business");
    await expect(kept[name]()).resolves.toBeTruthy();
  },
);
