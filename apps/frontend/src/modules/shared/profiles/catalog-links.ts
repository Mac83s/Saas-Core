import { stayFormHref, type StayPick } from "@saas-core/site-blocks";

/**
 * A company's booking form as the catalogue links it (ADR-072 §11, slice
 * 5h): what the visitor already chose, and `origin` — the catalogue's signed
 * word for where they come from. The form sends it back with the booking,
 * which then says „Katalog”; it travels in the address, never in a cookie.
 */
export function catalogFormHref(
  booking: { form_url: string; origin: string },
  pick: StayPick = {},
): string {
  const href = stayFormHref(booking.form_url, pick);
  return `${href}${href.includes("?") ? "&" : "?"}origin=${encodeURIComponent(booking.origin)}`;
}
