import type { ProductExtension } from "#lib/product-extension";

/**
 * The product slot (ADR-049). Saas-Core ships the general product, Business:
 * nothing of its own but the phone's bottom bar, where a company's website
 * matters more than its warehouse (owner's answer 44a). A product repository
 * replaces this file — the one core frontend file it may change — and keeps
 * everything else it adds in files of its own.
 */
export const product: ProductExtension = {
  mobileTabs: ["/panel", "/panel/calendar", "/panel/sites"],
};
