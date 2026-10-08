import type { SiteSitemapEntry } from "#lib/product-site/table";

/**
 * The product's public pages for `sitemap.xml` (ADR-080): which pages of its
 * table exist, with which parameters and in which languages. Names pages,
 * never addresses — the core writes every address and every language
 * alternate from the table. Read on the server only, on each request for the
 * sitemap, so it may ask the backend. Saas-Core ships none.
 */
export async function siteSitemap(): Promise<SiteSitemapEntry[]> {
  return [];
}
