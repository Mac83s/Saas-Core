import type { ProductDashboard } from "#lib/product-extension";

/**
 * The product slot for "Today" (ADR-049). Saas-Core has none, so /panel shows
 * core's start page; a product repository replaces this file with its own.
 */
const dashboard: ProductDashboard | null = null;

export default dashboard;
