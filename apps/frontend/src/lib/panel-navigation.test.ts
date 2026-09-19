import { describe, expect, it } from "vitest";

import { billingAttention } from "./billing-attention";
import { isActive, panelNavigation, sectionTabs } from "./panel-navigation";

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
  it("SEO jest zakładką Strony, a jej menu świeci się na obu", () => {
    const tabs = sectionTabs("/panel/seo/search-console", OWNER);
    expect(tabs?.map((tab) => tab.href)).toEqual([
      "/panel/sites",
      "/panel/seo",
    ]);

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
