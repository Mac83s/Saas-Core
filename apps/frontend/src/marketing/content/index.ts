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
