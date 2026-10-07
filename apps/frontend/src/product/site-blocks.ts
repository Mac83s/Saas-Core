import type { ProductSiteBlocks } from "#lib/product-extension";

/**
 * The block types this product's modules bring to the site builder (ADR-077).
 * Saas-Core ships none: every block of the general product is the core's own.
 * A product repository replaces this file with the sets of its modules —
 * `export const siteBlocks = [breedBlocks]`, each set a file of the module's
 * own (docs/architecture/site-block-types.md).
 */
export const siteBlocks: ProductSiteBlocks = [];
