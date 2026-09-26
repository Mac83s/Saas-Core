import { describe, expect, it, vi } from "vitest";

import { billingAttention } from "./billing-attention";

// A product that adds a settings tab of its own, for its own module only.
vi.mock("../product", () => ({
  product: {
    settingsSections: [
      {
        href: "/panel/settings/field-work",
        labelKey: "fieldWork",
        module: "vertical.demo",
      },
    ],
  },
}));
import {
  currentPage,
  isActive,
  panelNavigation,
  sectionTabs,
  type PanelAccess,
} from "./panel-navigation";

const OWNER = {
  modules: [
    "shared.billing",
    "shared.sites",
    "shared.seo",
    "shared.notifications",
  ],
  permissions: null,
  isOwner: true,
  limited: false,
};

describe("sekcje menu", () => {
  it("Zespół to Pracownicy i Role; karta osoby świeci się pod Pracownikami", () => {
    const team: PanelAccess = {
      ...OWNER,
      permissions: ["organization.members.read"],
    };
    const tabs = sectionTabs("/panel/team/s-marcin/schedule", team);
    expect(tabs?.map((tab) => tab.href)).toEqual([
      "/panel/team",
      "/panel/team/roles",
    ]);
    expect(currentPage("/panel/team/s-marcin/schedule", tabs!)).toBe(
      "/panel/team",
    );
    expect(currentPage("/panel/team/roles", tabs!)).toBe("/panel/team/roles");
    const entry = panelNavigation(team).company.find(
      (item) => item.labelKey === "team",
    )!;
    expect(entry.pages?.map((page) => page.labelKey)).toEqual([
      "teamPeople",
      "teamRoles",
    ]);
    // A trimmer without the team screen has no tabs to be shown either.
    expect(
      sectionTabs("/panel/team/me", { ...OWNER, permissions: [] }),
    ).toBeNull();
  });

  it("SEO jest zakładką Strony, a jej menu świeci się na obu", () => {
    const tabs = sectionTabs("/panel/seo/search-console", OWNER);
    expect(tabs?.map((tab) => tab.href)).toEqual([
      "/panel/sites",
      "/panel/seo",
      "/panel/seo/search-console",
    ]);
    // The deepest page is the current one, not its parent that also matches.
    expect(currentPage("/panel/seo/search-console", tabs!)).toBe(
      "/panel/seo/search-console",
    );

    const website = panelNavigation(OWNER).company.find(
      (item) => item.href === "/panel/sites",
    )!;
    expect(isActive("/panel/seo/search-console", website)).toBe(true);
    expect(isActive("/panel/settings/credits", website)).toBe(false);
  });

  it("bez drugiej widocznej zakładki nie ma paska zakładek", () => {
    const withoutSeoPermission = {
      ...OWNER,
      permissions: ["site.content.edit"],
    };
    expect(sectionTabs("/panel/sites", withoutSeoPermission)).toBeNull();
    expect(sectionTabs("/panel/calendar", OWNER)).toBeNull();
  });

  it("kredyty bez planu i płatności dla nie-właściciela", () => {
    expect(
      sectionTabs("/panel/settings/credits", { ...OWNER, isOwner: false }),
    ).toBeNull();
  });
});

describe("ustawienia", () => {
  const settings = (access: PanelAccess) =>
    panelNavigation(access).company.at(-1)!;
  /** A limited role: daily work, none of the company's settings. */
  const LIMITED = {
    ...OWNER,
    modules: [...OWNER.modules, "shared.booking"],
    permissions: ["booking.appointment.read", "organization.read"],
    isOwner: false,
    limited: true,
  };

  it("Firma, Historia zmian, Konto, Usługi i grafik, Zaawansowane, a na końcu zakładki produktu", () => {
    const tabs = sectionTabs("/panel/settings/account", {
      ...OWNER,
      modules: [...OWNER.modules, "shared.booking", "vertical.demo"],
    });
    expect(tabs?.map((tab) => tab.href)).toEqual([
      "/panel/settings/company",
      "/panel/settings/history",
      "/panel/settings/account",
      "/panel/settings/services",
      "/panel/integrations",
      "/panel/settings/field-work",
    ]);
  });

  it("zakładka produktu tylko z jej modułem, usługi tylko z rezerwacjami", () => {
    expect(
      sectionTabs("/panel/settings/account", OWNER)?.map((tab) => tab.href),
    ).toEqual([
      "/panel/settings/company",
      "/panel/settings/history",
      "/panel/settings/account",
      "/panel/integrations",
    ]);
  });

  it("„Ustawienia” prowadzą do pierwszej zakładki, którą osoba może otworzyć", () => {
    expect(settings(OWNER).href).toBe("/panel/settings/company");
    expect(isActive("/panel/settings/services", settings(OWNER))).toBe(true);
    expect(isActive("/panel/integrations", settings(OWNER))).toBe(true);

    expect(settings(LIMITED).href).toBe("/panel/settings/account");
    // Their only tab: no tab bar to choose from.
    expect(sectionTabs("/panel/settings/account", LIMITED)).toBeNull();
  });
});

describe("abonament w menu", () => {
  const NOW = Date.parse("2026-09-19T12:00:00Z");
  const subscription = (
    state: string,
    trial_end: string | null = null,
    access_mode: string | null = "full",
  ) => ({
    state,
    trial_end,
    access_mode,
    plan_key: "profile",
    plan_version: 1,
    current_period_end: null,
    grace_period_end: null,
    cancel_at_period_end: false,
  });

  it("aktywny plan nie woła o uwagę", () => {
    expect(billingAttention(subscription("active"), NOW)).toBeNull();
  });

  it("okres próbny liczy pełne dni, ostatni to „kończy się dziś”", () => {
    expect(
      billingAttention(subscription("trialing", "2026-09-24T08:00:00Z"), NOW),
    ).toEqual({ kind: "trial", days: 4 });
    expect(
      billingAttention(subscription("trialing", "2026-09-19T20:00:00Z"), NOW),
    ).toEqual({ kind: "trial", days: 0 });
    expect(
      billingAttention(subscription("trialing", "2026-09-18T08:00:00Z"), NOW),
    ).toEqual({ kind: "trial", days: 0 });
  });

  it("brak planu, nieudana płatność i blokada mają swoje komunikaty", () => {
    expect(billingAttention(null, NOW)).toEqual({ kind: "noPlan" });
    expect(billingAttention(subscription("grace_period"), NOW)).toEqual({
      kind: "payment",
    });
    expect(billingAttention(subscription("suspended"), NOW)).toEqual({
      kind: "limited",
    });
  });

  it("anulowany plan: do końca okresu ostrzeżenie, potem ograniczony dostęp", () => {
    expect(billingAttention(subscription("canceled"), NOW)).toEqual({
      kind: "canceled",
    });
    expect(
      billingAttention(subscription("canceled", null, "read_only"), NOW),
    ).toEqual({ kind: "limited" });
  });
});

describe("website inquiry access", () => {
  const messages = (modules: string[], permissions: string[]) =>
    panelNavigation({
      ...OWNER,
      modules,
      permissions,
      isOwner: false,
    }).company.some((item) => item.href.startsWith("/panel/notifications"));
  it("offers messages to website editors without automation permission", () => {
    expect(
      messages(["shared.notifications", "shared.sites"], ["site.content.edit"]),
    ).toBe(true);
    expect(messages(["shared.notifications"], ["site.content.edit"])).toBe(
      false,
    );
    expect(messages(["shared.notifications", "shared.sites"], [])).toBe(false);
    expect(messages(["shared.notifications"], ["notifications.manage"])).toBe(
      true,
    );
  });
});

describe("podstrony w menu (ADR-057)", () => {
  const WAREHOUSE = {
    ...OWNER,
    modules: [...OWNER.modules, "shared.inventory"],
  };
  const inventory = (access: PanelAccess) =>
    panelNavigation(access).work.find((item) => item.labelKey === "inventory");

  it("magazyn rozwija się na strony, które osoba może otworzyć", () => {
    expect(inventory(WAREHOUSE)?.pages?.map((page) => page.href)).toEqual([
      "/panel/inventory",
      "/panel/inventory/items",
      "/panel/inventory/lots",
      "/panel/inventory/documents",
      "/panel/inventory/settings",
    ]);
    // A worker without inventory.manage sees their stock and the catalogue.
    expect(
      inventory({
        ...WAREHOUSE,
        permissions: ["inventory.read"],
      })?.pages?.map((page) => page.href),
    ).toEqual(["/panel/inventory", "/panel/inventory/items"]);
    expect(
      currentPage("/panel/inventory/items", inventory(WAREHOUSE)!.pages!),
    ).toBe("/panel/inventory/items");
    expect(currentPage("/panel/inventory", inventory(WAREHOUSE)!.pages!)).toBe(
      "/panel/inventory",
    );
  });

  it("jedna dostępna strona to sama pozycja, bez rozwijania", () => {
    const messages = panelNavigation({
      ...OWNER,
      permissions: ["notifications.manage"],
      isOwner: false,
    }).company.find((item) => item.labelKey === "messages");
    expect(messages?.href).toBe("/panel/notifications/automation");
    expect(messages?.pages).toBeUndefined();
  });
});
