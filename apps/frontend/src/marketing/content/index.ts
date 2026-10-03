import { notFound } from "next/navigation";

import { isMarketingLocale } from "#i18n/routing";
import { deployment } from "../../generated/deployment";
import { product } from "../../product";
import { business } from "./business";
import type { MarketingLocale, ProductCopy } from "./types";

export type { MarketingLocale, ProductCopy } from "./types";

/** The product's copy from its slot (ADR-049); the generic product otherwise. */
export function productCopy(locale: string): ProductCopy {
  const content = product.marketing ?? business;
  return content[(locale === "en" ? "en" : "pl") satisfies MarketingLocale];
}

export const productName = deployment.product.name;

/** The company catalogue (ADR-053) is part of every product that composes profiles. */
export const productHasCatalog = (
  deployment.modules as readonly string[]
).includes("shared.profiles");

/**
 * A marketing page exists only in a language the product has copy in
 * (TL17): `/de/pricing` without German copy is a 404, not English copy under
 * a German address. The catalogue is not a marketing page.
 */
export function requireMarketingLocale(locale: string): void {
  if (!isMarketingLocale(locale)) notFound();
}
