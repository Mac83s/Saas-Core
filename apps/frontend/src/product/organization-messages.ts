import type { OrganizationTypeMessages } from "#lib/product-extension";

/**
 * The product slot for the panel's words that depend on the kind of
 * organization (ADR-049, UX-080). Saas-Core has none. A product with more
 * than one organization type replaces this file: a farm says „Wizytówka
 * gospodarstwa” where a trimming company keeps „Wizytówka firmy”. Only the
 * panel of that type gets them (`getPanelMessages`); every other account, the
 * public pages and the sign-in keep the product's messages.
 */
const organizationMessages: OrganizationTypeMessages = {};

export default organizationMessages;
