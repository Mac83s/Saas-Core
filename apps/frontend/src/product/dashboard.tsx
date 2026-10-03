import type { ProductDashboards } from "#lib/product-extension";

/**
 * The product slot for "Today" (ADR-049). Saas-Core has none, so /panel shows
 * core's start page; a product repository replaces this file with its own, and
 * its `module`/`organizationTypes`/`permission` say for whom — everyone else
 * keeps core's start page. A list gives each kind of organization its own,
 * e.g. a farm the core `FarmerToday` from `shared.farms` (UX-078).
 */
const dashboard: ProductDashboards = null;

export default dashboard;
