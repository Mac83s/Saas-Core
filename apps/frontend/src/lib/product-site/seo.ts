import type { Metadata, MetadataRoute } from "next";

import type {
  CompiledOldAddresses,
  CompiledSite,
  SiteParams,
  SiteSitemapEntry,
  SiteVersion,
  SiteVersions,
} from "#lib/product-site/table";
import { deployment } from "../../generated/deployment";
import { openGraphLocale } from "../../marketing/seo";
import { productOldAddresses } from "./old-addresses";
import { productSite } from "./site";

const origin = `https://${deployment.product.platformDomain}`;

type Alternates = { canonical: string; languages: Record<string, string> };

/**
 * A page's address in each language it answers in today: the table's
 * versions without any address an old-address rule answers instead. The one
 * filter behind hreflang, the sitemap and the language switch, so the page's
 * head, its switch and the sitemap name the same addresses.
 */
function answering(
  site: CompiledSite,
  rules: CompiledOldAddresses | null,
  route: string,
  params?: SiteParams | SiteVersions,
): SiteVersion[] {
  return site
    .versions(route, params)
    .filter((version) => !rules?.lookup(version.path));
}

/**
 * The language switch of a page (ADR-080): its address in every language it
 * answers in, from the table. Server side only — it reads the old-address
 * rules, which stay out of a page's bundle; a client component is handed
 * the result.
 */
export function siteVersions(
  route: string,
  params?: SiteParams | SiteVersions,
): SiteVersion[] {
  if (!productSite) {
    throw new Error("This deployment serves no public pages of the product.");
  }
  return answering(productSite, productOldAddresses, route, params);
}

/** hreflang for every language the page answers in, and x-default: the
 *  default language's version, or the first where it has none. */
function languagesOf(
  site: CompiledSite,
  route: string,
  params?: SiteParams | SiteVersions,
): Record<string, string> {
  const versions = answering(site, productOldAddresses, route, params);
  const base =
    versions.find((version) => version.locale === site.defaultLocale) ??
    versions[0];
  return {
    ...Object.fromEntries(
      versions.map((version) => [version.locale, `${origin}${version.path}`]),
    ),
    ...(base ? { "x-default": `${origin}${base.path}` } : {}),
  };
}

/**
 * A page's canonical address and its language alternates (ADR-080), from the
 * table that routes it. `params` are the same in every language, or per
 * language where the page's own name is translated (`{ pl: { slug: … }, en:
 * { slug: … } }`) — a language left out is not named in hreflang.
 */
export function siteAlternates(args: {
  route: string;
  locale: string;
  params?: SiteParams | SiteVersions;
}): Alternates {
  if (!productSite) {
    throw new Error("This deployment serves no public pages of the product.");
  }
  const languages = languagesOf(productSite, args.route, args.params);
  const canonical = languages[args.locale];
  if (!canonical) {
    throw new Error(
      `The page ${args.route} has no address in ${args.locale} with these parameters.`,
    );
  }
  return { canonical, languages };
}

/**
 * The metadata every public page of the product shares: canonical, hreflang
 * and Open Graph. One place, so no page writes an address by hand.
 */
export function siteMetadata(args: {
  route: string;
  locale: string;
  params?: SiteParams | SiteVersions;
  title: string;
  description: string;
}): Metadata {
  const alternates = siteAlternates(args);
  return {
    title: args.title,
    description: args.description,
    alternates,
    openGraph: {
      title: args.title,
      description: args.description,
      url: alternates.canonical,
      siteName: deployment.product.name,
      locale: openGraphLocale(args.locale),
      type: "website",
    },
  };
}

/**
 * The sitemap lines of the pages a product names: one per language a page
 * exists in, each naming all of them. An address that is an old-address rule
 * today is left out — it answers a redirect or 410, not a page.
 */
export function siteSitemapLines(
  site: CompiledSite,
  rules: CompiledOldAddresses | null,
  entries: readonly SiteSitemapEntry[],
): MetadataRoute.Sitemap {
  return entries.flatMap((entry) => {
    if (!site.routes.includes(entry.route)) {
      // One wrong line must not cost the whole sitemap its answer.
      console.error(
        `product public site: the sitemap names "${entry.route}", which is no page of the table`,
      );
      return [];
    }
    const versions = answering(site, rules, entry.route, entry.params);
    const base =
      versions.find((version) => version.locale === site.defaultLocale) ??
      versions[0];
    if (!base) return [];
    const languages = {
      ...Object.fromEntries(
        versions.map((version) => [version.locale, `${origin}${version.path}`]),
      ),
      "x-default": `${origin}${base.path}`,
    };
    return versions.map((version) => ({
      url: `${origin}${version.path}`,
      ...(entry.lastModified ? { lastModified: entry.lastModified } : {}),
      alternates: { languages },
    }));
  });
}
