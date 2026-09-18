import { deployment } from "../../generated/deployment";
import { business } from "./business";
import { hoofcare } from "./hoofcare";
import { medplano } from "./medplano";
import type { MarketingLocale, ProductContent, ProductCopy } from "./types";

export type { MarketingLocale, ProductCopy } from "./types";

/** Copy per deployment profile; every other profile is the generic product. */
const BY_PROFILE: Record<string, ProductContent> = { hoofcare, medplano };

export function productCopy(locale: string): ProductCopy {
  const content = BY_PROFILE[deployment.id] ?? business;
  return content[(locale === "en" ? "en" : "pl") satisfies MarketingLocale];
}

export const productName = deployment.product.name;
