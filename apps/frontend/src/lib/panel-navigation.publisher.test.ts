import type { LucideIcon } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import type { OrganizationSummary } from "@saas-core/api-client";

// A product as HoofCare or MedPlano compose one: two kinds of organization,
// a module of its own, its own menu entries, bottom bar and settings tab.
const SHARED = [
  "shared.model-port",
  "shared.billing",
  "shared.sites",
  "shared.media",
  "shared.profiles",
  "shared.notifications",
  "shared.translation",
  "shared.assistant",
  "shared.customers",
  "shared.commerce",
  "shared.booking",
  "shared.seo",
  "shared.inventory",
];
vi.mock("../generated/deployment", () => ({
  deployment: {
    modules: [
      "core.health",
      "core.identity",
      "core.organizations",
      ...SHARED,
      "vertical.demo",
    ],
    features: { customerRetention: true },
    organizationTypes: [
      {
        key: "company",
        label: { pl: "Firma", en: "Company" },
        description: null,
        modules: [...SHARED, "vertical.demo"],
        planKeys: ["pro"],
        selfSignup: true,
        roles: [
          {
            key: "trimmer",
            label: { pl: "Korektor", en: "Trimmer" },
            permissions: ["booking.appointment.read", "demo.read"],
            limited: true,
          },
        ],
        serviceTemplates: [],
      },
      {
        key: "farm",
        label: { pl: "Gospodarstwo", en: "Farm" },
        description: null,
        modules: ["shared.billing", "shared.sites"],
        planKeys: ["farm"],
        selfSignup: false,
        roles: [],
        serviceTemplates: [],
      },
    ],
  },
}));
const icon = (() => null) as unknown as LucideIcon;
vi.mock("../product", () => ({
  product: {
    navigation: [
      {
        href: "/panel/breeds",
        icon,
        labelKey: "breeds",
        module: "vertical.demo",
        permission: "demo.read",
      },
      // A product's entry on a shared module a publisher is not offered.
      {
        href: "/panel/visits",
        icon,
        labelKey: "visits",
        module: "shared.booking",
      },
      {
        href: "/panel/reports",
        icon,
        labelKey: "reports",
        module: "vertical.demo",
        group: "company",
      },
    ],
    mobileTabs: ["/panel/calendar", "/panel/breeds"],
    settingsSections: [
      {
        href: "/panel/settings/field-work",
        labelKey: "fieldWork",
        module: "vertical.demo",
      },
    ],
  },
}));

const {
  goneForPublisher,
  menuEntryFor,
  mobileTabs,
  panelAccess,
  panelNavigation,
  panelSettings,
  sectionTabs,
  PUBLISHER_MODULES,
} = await import("./panel-navigation");

// Core's owner (`core.organizations.permissions`) with the product's own right.
const OWNER = [
  "organization.read",
  "organization.members.read",
  "organization.members.manage",
  "organization.settings.manage",
  "organization.billing.manage",
  "booking.appointment.read",
  "booking.appointment.manage",
  "booking.staff.performance.read",
  "commerce.orders.read",
  "customers.read",
  "inventory.read",
  "inventory.manage",
  "notifications.manage",
  "integrations.manage",
  "profiles.manage",
  "seo.audit.read",
  "site.content.edit",
  "assistant.use",
  "demo.read",
];

function organization(
  overrides: Partial<OrganizationSummary> = {},
): OrganizationSummary {
  return {
    id: "019f0000-0000-7000-8000-000000000001",
    name: "Serwis",
    slug: "serwis",
    workspace_kind: "business",
    organization_type: "company",
    status: "active",
    default_locale: "pl",
    timezone: "Europe/Warsaw",
    currency: "PLN",
    version: 1,
    membership_status: "active",
    role: "owner",
    permissions: OWNER,
    active: true,
    ...overrides,
  };
}

const keys = (items: { labelKey: string }[]) =>
  items.map((item) => item.labelKey);
const hrefs = (items: { href: string }[]) => items.map((item) => item.href);

describe("workspace platformy: panel wydawcy (ADR-077 pkt 9)", () => {
  const publisher = panelAccess(organization({ workspace_kind: "platform" }));

  it("z modułów wspólnych zostają te, z których korzysta wydawca; rdzeń i moduł produktu zostają", () => {
    expect(publisher.publisher).toBe(true);
    expect(publisher.modules).toEqual([
      "core.health",
      "core.identity",
      "core.organizations",
      "shared.model-port",
      "shared.sites",
      "shared.media",
      "shared.translation",
      "vertical.demo",
    ]);
    // What the API refuses is the API's to say: the membership's rights are
    // passed on as they are.
    expect(publisher.permissions).toEqual(OWNER);
    // Generated images are a plan feature the workspace is not granted.
    expect(PUBLISHER_MODULES).not.toContain("shared.image-generation");
  });

  it("menu: „Treści platformy” pod „Pracą” z wpisami produktu, „Ustawienia” pod „Firmą” — bez „Wiadomości”", () => {
    const menu = panelNavigation(publisher);
    expect(keys(menu.work)).toEqual(["today", "platformContent", "breeds"]);
    expect(keys(menu.company)).toEqual(["reports", "settings"]);
    expect(menu.platform).toEqual([]);
    expect(
      hrefs(panelNavigation({ ...publisher, operatorLevel: 1 }).platform),
    ).toEqual(["/panel/platform"]);
  });

  it("„Treści platformy” to treści, tłumaczenia i integracje — bez ekranów kreatora stron (ADR-079 pkt 29)", () => {
    const menu = panelNavigation(publisher);
    const content = menu.work.find(
      (item) => item.labelKey === "platformContent",
    )!;
    expect(content.group).toBe("work");
    // „Treści”, though this profile offers companies no content types: the
    // switch is about companies, the workspace runs its own (ADR-079 pkt 28).
    // No pages, menu, publication of a site or address: no host serves the
    // workspace's builder site.
    expect(hrefs(content.pages!)).toEqual([
      "/panel/sites/content",
      "/panel/sites/translations",
      "/panel/sites/integrations",
    ]);
    // The entry opens its first page — not „Podstrony”, which is gone.
    expect(content.href).toBe("/panel/sites/content");
    expect(hrefs(sectionTabs("/panel/sites/translations", publisher)!)).toEqual(
      hrefs(content.pages!),
    );
  });

  it("żaden wpis menu nie prowadzi do ekranu kreatora ani do zapytań z jego formularzy", () => {
    const menu = panelNavigation({ ...publisher, operatorLevel: 1 });
    const offered = [...menu.work, ...menu.company, ...menu.platform].flatMap(
      (item) => [item.href, ...(item.pages ?? []).map((page) => page.href)],
    );
    for (const gone of [
      "/panel/sites",
      "/panel/sites/menu",
      "/panel/sites/publication",
      "/panel/sites/address",
      "/panel/notifications",
    ])
      expect(offered).not.toContain(gone);
    expect(
      offered.filter((href) => href.startsWith("/panel/sites/pages")),
    ).toEqual([]);
  });

  it("zna adresy, których panel wydawcy nie ma — żeby wspólny ekran do nich nie prowadził", () => {
    for (const gone of [
      "/panel/sites",
      "/panel/sites?site=019f0000",
      "/panel/sites/pages/019f0000",
      "/panel/sites/pages/019f0000?language=en",
      "/panel/sites/menu",
      "/panel/sites/publication",
      "/panel/sites/address",
      "/panel/notifications",
    ])
      expect(goneForPublisher(gone), gone).toBe(true);
    for (const kept of [
      "/panel",
      "/panel/sites/content",
      "/panel/sites/content/019f0000/categories",
      "/panel/sites/blog?site=019f0000",
      "/panel/sites/translations",
      "/panel/sites/integrations",
      "/panel/settings/languages",
    ])
      expect(goneForPublisher(kept), kept).toBe(false);
  });

  it("nagłówek strony bierze nazwę z menu wydawcy, a w firmie z menu firmy", () => {
    expect(menuEntryFor("/panel/sites/content", publisher)?.labelKey).toBe(
      "platformContent",
    );
    expect(menuEntryFor("/panel/sites/content")?.labelKey).toBe("website");
    expect(
      menuEntryFor("/panel/sites/content", panelAccess(organization()))
        ?.labelKey,
    ).toBe("website");
  });

  it("ustawienia: dane, języki, historia, konto i zakładka produktu — bez usług, rezerwacji, dokumentów i API", () => {
    const settings = panelNavigation({
      ...publisher,
      settingsAreas: [{ key: "security", label: "Bezpieczeństwo" }],
    }).company.find((item) => item.labelKey === "settings")!;
    expect(hrefs(settings.pages!)).toEqual([
      "/panel/settings/company",
      "/panel/settings/security",
      "/panel/settings/languages",
      "/panel/settings/history",
      "/panel/settings/account",
      "/panel/settings/field-work",
    ]);
  });

  it("nie prowadzi do niczego, co wymaga planu, abonamentu, zaproszeń albo modułu spoza listy", () => {
    const menu = panelNavigation({ ...publisher, operatorLevel: 1 });
    const offered = [...menu.work, ...menu.company, ...menu.platform].flatMap(
      (item) => [item.href, ...(item.pages ?? []).map((page) => page.href)],
    );
    for (const refused of [
      "/panel/calendar",
      "/panel/inventory",
      "/panel/orders",
      "/panel/assistant",
      "/panel/visits",
      "/panel/team",
      "/panel/profile",
      "/panel/seo",
      "/panel/notifications/automation",
      "/panel/integrations",
      "/panel/settings/billing",
      "/panel/settings/credits",
      "/panel/settings/services",
      "/panel/settings/bookings",
      "/panel/settings/documents",
      "/panel/settings/consents",
      "/panel/settings/customer-removal",
    ])
      expect(offered.filter((href) => href.startsWith(refused))).toEqual([]);
  });

  it("dolny pasek telefonu: wpis produktu, „Dziś” i treści — kalendarza z listy produktu tu nie ma", () => {
    expect(keys(mobileTabs(publisher))).toEqual([
      "breeds",
      "today",
      "platformContent",
    ]);
  });

  it("bez prawa do treści strony zostaje „Dziś” i to, co wnosi produkt", () => {
    const reader = panelAccess(
      organization({
        workspace_kind: "platform",
        role: "viewer",
        permissions: ["organization.read", "demo.read"],
      }),
    );
    const menu = panelNavigation(reader);
    expect(keys(menu.work)).toEqual(["today", "breeds"]);
    expect(keys(menu.company)).toEqual(["reports", "settings"]);
  });

  it("ustawienia: tylko grupy modułów wydawcy i obszary, w których coś zostało — bez zapytań z formularza kreatora", () => {
    const group = (key: string, module: string, area: string) =>
      ({ key, module, area }) as never;
    const area = (key: string) => ({ key, page: null }) as never;
    const schema = {
      areas: [
        area("privacy"),
        area("inventory"),
        area("site-inquiries"),
        area("translation"),
      ],
      groups: [
        group("booking.retention", "shared.booking", "privacy"),
        group("sites.retention", "shared.sites", "privacy"),
        group("inventory.alerts", "shared.inventory", "inventory"),
        group("sites.inquiries", "shared.sites", "site-inquiries"),
        group("translation.settings", "shared.translation", "translation"),
      ],
    };
    const shown = panelSettings(schema, publisher);
    // Who is told of an enquiry and how long one is kept are about a builder
    // site's contact form, which this workspace has none of (ADR-079 pkt 29).
    expect(shown.groups.map((item) => item.key)).toEqual([
      "translation.settings",
    ]);
    expect(shown.areas.map((item) => item.key)).toEqual(["translation"]);
    // A company's settings are the schema itself.
    expect(panelSettings(schema, panelAccess(organization()))).toBe(schema);
  });
});

describe("firma w produkcie: menu takie jak przed panelem wydawcy", () => {
  it("właściciel firmy: pełne menu rdzenia z wpisami produktu", () => {
    const access = panelAccess(organization());
    expect(access.publisher).toBeUndefined();
    const menu = panelNavigation(access);
    expect(keys(menu.work)).toEqual([
      "today",
      "calendar",
      "inventory",
      "orders",
      "assistant",
      "breeds",
      "visits",
    ]);
    expect(keys(menu.company)).toEqual([
      "team",
      "profile",
      "website",
      "messages",
      "billing",
      "reports",
      "settings",
    ]);
    expect(
      menu.company.find((item) => item.labelKey === "website")!.group,
    ).toBe("company");
    expect(
      hrefs(menu.company.find((item) => item.labelKey === "website")!.pages!),
    ).toContain("/panel/seo");
    expect(
      hrefs(menu.company.find((item) => item.labelKey === "messages")!.pages!),
    ).toEqual(["/panel/notifications", "/panel/notifications/automation"]);
    expect(keys(mobileTabs(access))).toEqual(["calendar", "breeds", "today"]);
  });

  it("ograniczona rola typu i drugi typ organizacji: bez zmian", () => {
    const trimmer = panelAccess(
      organization({
        role: "trimmer",
        permissions: ["booking.appointment.read", "demo.read"],
      }),
    );
    expect(trimmer.limited).toBe(true);
    expect(keys(panelNavigation(trimmer).work)).toEqual([
      "today",
      "calendar",
      "breeds",
      "visits",
    ]);
    expect(keys(panelNavigation(trimmer).company)).toEqual([
      "reports",
      "settings",
    ]);

    const farm = panelAccess(
      organization({ organization_type: "farm", workspace_kind: "personal" }),
    );
    expect(farm.publisher).toBeUndefined();
    expect(farm.modules).toEqual([
      "core.health",
      "core.identity",
      "core.organizations",
      "shared.billing",
      "shared.sites",
    ]);
    expect(keys(panelNavigation(farm).work)).toEqual(["today"]);
    expect(keys(panelNavigation(farm).company)).toEqual([
      "team",
      "website",
      "billing",
      "settings",
    ]);
  });
});
