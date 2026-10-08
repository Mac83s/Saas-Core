import type { ReservedSegments } from "#lib/product-site";

/**
 * The first path segment of an address on the platform host, after any
 * language prefix: whose page it is. One list, because the proxy routes by
 * it and a product's table of public addresses (ADR-080) is refused by it.
 */

/** The team's pages. */
export const PANEL_SEGMENTS: ReadonlySet<string> = new Set([
  "panel",
  "settings",
  "invitations",
  "login",
  "register",
  "onboarding",
  "password-reset",
  "reset-password",
  "verify-email",
]);

/** What a company's guest opens on the platform host: the booking form, a
 *  visit's own page, a company's document. Not marketing — they stay where
 *  the profile switches the marketing off (`features.marketingSite`). */
export const GUEST_SEGMENTS: ReadonlySet<string> = new Set([
  "book",
  "booking",
  "documents",
]);

/**
 * What the platform answers itself, before any page: the gateway's own
 * prefixes (`/internal`, `/static`), the published media of the platform's
 * own content (`/media`, ADR-079), the customer sites' renderer and the
 * folder a product's public pages are files in.
 */
const PLATFORM_SEGMENTS = [
  "media",
  "internal",
  "static",
  "site-renderer",
  "product-site",
];

/** What a product's public addresses and old-address rules may not name. */
export const RESERVED_SEGMENTS: ReservedSegments = {
  exact: new Set([...PANEL_SEGMENTS, ...GUEST_SEGMENTS, ...PLATFORM_SEGMENTS]),
  // The proxy's matcher skips every path that starts with one of these, so
  // `/api`, but also `/apiary`, is never seen by it.
  prefixes: ["api", "healthz", "_next", "_vercel"],
};
