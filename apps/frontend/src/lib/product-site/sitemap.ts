import type { MetadataRoute } from "next";

import { productOldAddresses } from "./old-addresses";
import { siteSitemapLines } from "./seo";
import { productSite } from "./site";

/**
 * The product's public pages in `sitemap.xml` (ADR-080); nothing where the
 * deployment serves none. The product's list is asked for only then, so a
 * deployment without public pages never loads it.
 */
export async function productSiteSitemap(): Promise<MetadataRoute.Sitemap> {
  if (!productSite) return [];
  const { siteSitemap } = await import("../../product/site-sitemap");
  return siteSitemapLines(
    productSite,
    productOldAddresses,
    await siteSitemap(),
  );
}
