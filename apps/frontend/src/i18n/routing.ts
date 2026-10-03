import { defineRouting } from "next-intl/routing";

import { deployment } from "../generated/deployment";

/**
 * Two kinds of language (TL17, ADR-071 pkt 1). The panel, sign-in and
 * invitations speak the team's languages; the guest pages — the catalogue,
 * booking, a customer's own link — speak every content language the profile
 * offers. A route group answers only in its own.
 */
export const panelLocales = ["pl", "en"] as const;
export const contentLocales: readonly string[] =
  deployment.product.supportedLocales;
/** The product's marketing copy exists in these only (`productCopy`). */
export const marketingLocales = ["pl", "en"] as const;

export const routing = defineRouting({
  locales: [...new Set<string>([...panelLocales, ...contentLocales])],
  defaultLocale: "pl",
  localePrefix: "as-needed",
});

export type AppLocale = (typeof routing.locales)[number];
export type PanelLocale = (typeof panelLocales)[number];

export function isPanelLocale(locale: string): locale is PanelLocale {
  return (panelLocales as readonly string[]).includes(locale);
}

export function isMarketingLocale(locale: string): boolean {
  return (marketingLocales as readonly string[]).includes(locale);
}
