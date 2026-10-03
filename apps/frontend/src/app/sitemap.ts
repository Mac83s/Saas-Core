import type { MetadataRoute } from "next";

import { marketingLocales, routing } from "#i18n/routing";
import { localizedUrl } from "../marketing/seo";
import { productCopy, productHasCatalog } from "../marketing/content";
import { cardLanguages } from "../modules/shared/profiles/catalog-seo";
import {
  readCatalogLocalesOnServer,
  readCatalogSitemapOnServer,
} from "../modules/shared/profiles/catalog-server";

// The catalogue changes between deploys: read at request time, not at build.
export const dynamic = "force-dynamic";

const PATHS = ["/", "/pricing", "/contact"];

/** One URL per language, each naming all of them and x-default. */
function inLanguages(
  path: string,
  locales: readonly string[],
  base: string,
  lastModified?: string,
): MetadataRoute.Sitemap {
  const languages = {
    ...Object.fromEntries(
      locales.map((locale) => [locale, localizedUrl(locale, path)]),
    ),
    "x-default": localizedUrl(base, path),
  };
  return locales.map((locale) => ({
    url: localizedUrl(locale, path),
    ...(lastModified ? { lastModified } : {}),
    alternates: { languages },
  }));
}

/**
 * The product's marketing pages and the catalogue (TL20); customer sites have
 * their own under `/site-renderer`. A card is listed in each routed language
 * it is whole in — never in one it only falls back from. Without the backend
 * the sitemap still lists the product's pages and the catalogue listing.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const paths = [
    ...PATHS,
    ...(productCopy("pl").pages ?? []).map((page) => `/${page.slug}`),
  ];
  const marketing = paths.flatMap((path) =>
    inLanguages(path, marketingLocales, routing.defaultLocale),
  );
  if (!productHasCatalog) return marketing;

  const [speaking, cards] = await Promise.all([
    readCatalogLocalesOnServer(),
    readCatalogSitemapOnServer(),
  ]);
  const listed = speaking
    ? routing.locales.filter((locale) => speaking.includes(locale))
    : [...routing.locales];
  const listing = listed.length
    ? inLanguages("/katalog", listed, listed[0] ?? routing.defaultLocale)
    : [];
  const entries = (cards ?? []).flatMap((card) => {
    const whole = cardLanguages(card, routing.locales);
    if (whole.length === 0) return [];
    const base = whole.includes(card.source_locale)
      ? card.source_locale
      : (whole[0] ?? card.source_locale);
    return inLanguages(
      `/katalog/${card.city_slug}/${card.slug}`,
      whole,
      base,
      card.updated_at,
    );
  });
  return [...marketing, ...listing, ...entries];
}
