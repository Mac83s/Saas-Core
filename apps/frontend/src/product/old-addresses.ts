import type { ProductOldAddresses } from "#lib/product-site";

/**
 * Addresses of the site this product's public pages replace (ADR-080): where
 * each one moved (one 308) or that it is gone (410). Saas-Core ships none.
 *
 * Data only, and a file of its own: the proxy reads it on every request, the
 * browser never does — a few thousand rules do not belong in a page's
 * bundle. A long list may live in a json file next to this one.
 */
export const oldAddresses: ProductOldAddresses = {};
