import type { ProductDashboard } from "#lib/product-extension";

/**
 * The product slot for "Today" (ADR-049). Saas-Core has none, so /panel shows
 * core's start page; a product repository replaces this file with its own, and
 * its `module`/`organizationTypes`/`permission` say for whom — everyone else
 * keeps core's start page.
 */
const dashboard: ProductDashboard | null = null;

export default dashboard;
