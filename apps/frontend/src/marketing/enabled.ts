import { deployment } from "../generated/deployment";

/**
 * Whether this deployment shows the core's marketing pages and the company
 * catalogue on its platform host (`features.marketingSite` in
 * `deployment.json`; on unless the profile says `false`).
 *
 * A product whose public site is built in the site builder (ADR-077) answers
 * visitors on its own domain and switches this off: the platform host is then
 * the panel only — `/` leads to sign-in, the marketing addresses answer 404
 * and the sitemap lists none. A file of its own, with no imports beyond the
 * profile, because the proxy reads it too.
 */
export const marketingSiteEnabled =
  (deployment.features as Record<string, unknown>).marketingSite !== false;
