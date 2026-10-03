import "server-only";

import type { CatalogDictionary, CatalogProfile } from "@saas-core/api-client";

const backendUrl = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";

/**
 * The public card page renders on the server, where the api-client's
 * same-origin relative URL cannot be fetched — Node's fetch needs an absolute
 * one, and every card page answered 500 until this read went to the backend
 * directly. `null` is a withdrawn or erased company: gone, not broken.
 */
export async function readCatalogProfileOnServer(
  city: string,
  slug: string,
  locale?: string,
): Promise<CatalogProfile | null> {
  // The card in the page's language where it is whole in it, its own
  // otherwise; `locale` in the answer says which (TL20).
  const query = locale ? `?locale=${encodeURIComponent(locale)}` : "";
  const response = await fetch(
    `${backendUrl}/api/v1/public/catalog/${encodeURIComponent(city)}/${encodeURIComponent(slug)}/${query}`,
    { cache: "no-store" },
  );
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`Public catalog API answered ${response.status}`);
  }
  return (await response.json()) as CatalogProfile;
}

/**
 * The languages some card is whole in, for the listing's metadata (TL20).
 * The dictionary, not the listing: the listing is throttled per client, and
 * every server-side read shares the frontend's address. `null` when the
 * backend does not answer: unknown is not "nobody", so the page stays indexed.
 */
export async function readCatalogLocalesOnServer(): Promise<string[] | null> {
  try {
    const response = await fetch(
      `${backendUrl}/api/v1/public/catalog/dictionary/`,
      { cache: "no-store" },
    );
    if (!response.ok) return null;
    return ((await response.json()) as CatalogDictionary).locales;
  } catch {
    return null;
  }
}

export type CatalogSitemapEntry = {
  city_slug: string;
  slug: string;
  source_locale: string;
  translated_locales: string[];
  updated_at: string;
};

/** Pages read at most: 8 × 5000 entries keeps one sitemap under 50 000 URLs
 * with two routed languages. A catalogue past that needs a sitemap index. */
const SITEMAP_PAGES = 8;

/**
 * Every catalogue address with its languages, for the platform's sitemap
 * (TL20). `null` when the backend does not answer, so the sitemap still
 * serves the product's own pages.
 */
export async function readCatalogSitemapOnServer(): Promise<
  CatalogSitemapEntry[] | null
> {
  const entries: CatalogSitemapEntry[] = [];
  try {
    for (let page = 1; page <= SITEMAP_PAGES; page += 1) {
      const response = await fetch(
        `${backendUrl}/api/v1/public/catalog/sitemap/?page=${page}`,
        { cache: "no-store" },
      );
      if (!response.ok) return null;
      const body = (await response.json()) as {
        page_size: number;
        items: CatalogSitemapEntry[];
      };
      entries.push(...body.items);
      if (body.items.length < body.page_size) break;
    }
  } catch {
    return null;
  }
  return entries;
}
