import type { ProductPublicSite } from "#lib/product-site/table";

/**
 * The product's public pages on its own host (ADR-080): which page file
 * answers which address, per language. Saas-Core ships none — its platform
 * host shows the core's marketing pages, or sign-in. A product replaces this
 * file; the contract is `docs/architecture/product-public-site.md`.
 *
 * Data only: the proxy and the browser both read this file, so it imports
 * nothing but its own type.
 */
export const publicSite: ProductPublicSite | null = null;
