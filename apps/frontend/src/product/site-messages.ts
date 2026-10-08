import type { SiteMessages } from "#lib/product-site";

/**
 * The words of the product's public pages, per content language (ADR-080) —
 * laid over the messages of that language, with the English ones underneath
 * a language that lacks a word. A file of its own, read on the server only:
 * `product` is imported by the menu on the client and would carry every
 * language's words into the panel. Saas-Core ships none.
 */
export const siteMessages: SiteMessages = {};
