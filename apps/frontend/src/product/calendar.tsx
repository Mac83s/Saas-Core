import type { ProductCalendar } from "#lib/product-extension";

/**
 * The product slot for the calendar (ADR-049, ADR-067). Saas-Core books every
 * visit with its own form, so it ships none. A product repository replaces
 * this file when a kind of visit of its own needs more than core asks — a
 * HoofCare herd visit, its farm.
 */
const calendar: ProductCalendar | null = null;

export default calendar;
