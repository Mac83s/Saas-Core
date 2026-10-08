import { describe, expect, it, vi } from "vitest";

import type { OrganizationSummary } from "@saas-core/api-client";

// A platform that offers companies content types beyond a site's first
// (`features.contentTypes`, ADR-079 pkt 21).
vi.mock("../generated/deployment", () => ({
  deployment: {
    modules: [
      "core.health",
      "core.identity",
      "core.organizations",
      "shared.billing",
      "shared.sites",
    ],
    features: { contentTypes: true },
    organizationTypes: [
      {
        key: "business",
        label: { pl: "Firma", en: "Business" },
        description: null,
        modules: ["shared.billing", "shared.sites"],
        planKeys: ["pro"],
        selfSignup: true,
        roles: [],
        serviceTemplates: [],
      },
    ],
  },
}));
vi.mock("../product", () => ({
  product: { navigation: [], mobileTabs: [], settingsSections: [] },
}));

const { offersContentTypes, panelAccess, sectionTabs } =
  await import("./panel-navigation");

const company = {
  id: "019ff20d-a000-7000-8000-000000000001",
  organization_type: "business",
  workspace_kind: "company",
  role: "owner",
  permissions: null,
} as unknown as OrganizationSummary;

describe("„Treści” w menu strony (ADR-079 pkt 25)", () => {
  it("zastępuje „Blog” tam, gdzie platforma oferuje typy treści", () => {
    const access = panelAccess(company);
    expect(offersContentTypes(access)).toBe(true);
    const tabs = sectionTabs("/panel/sites", access)!.map((tab) => tab.href);
    expect(tabs).toContain("/panel/sites/content");
    expect(tabs).not.toContain("/panel/sites/blog");
    expect(tabs.indexOf("/panel/sites/content")).toBe(
      tabs.indexOf("/panel/sites/menu") + 1,
    );
  });

  it("strony jednego typu świecą „Treści”, a stary adres bloga dalej ma swoje zakładki", () => {
    const access = panelAccess(company);
    const type = "/panel/sites/content/019ff20d-a000-7000-8000-000000000020";
    expect(sectionTabs(type, access)).not.toBeNull();
    expect(sectionTabs(`${type}/settings`, access)).not.toBeNull();
    expect(sectionTabs(`${type}/categories`, access)).not.toBeNull();
    expect(sectionTabs(`${type}/tags`, access)).not.toBeNull();
    // /panel/sites/blog still answers (links from translation jobs lead
    // there) and still stands among the site's pages.
    expect(sectionTabs("/panel/sites/blog", access)).not.toBeNull();
  });
});
