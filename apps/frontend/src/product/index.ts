import type { ProductExtension } from "#lib/product-extension";

/**
 * The product slot (ADR-049). Saas-Core ships it empty. A product repository
 * replaces this file — the one core frontend file it may change — and keeps
 * everything else it adds in files of its own.
 */
export const product: ProductExtension = {};
