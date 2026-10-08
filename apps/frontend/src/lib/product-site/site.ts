import {
  compileProductSite,
  type CompiledSite,
  type SiteParams,
} from "#lib/product-site/table";
import { contentLocales, routing } from "#i18n/routing";
import { marketingSiteEnabled } from "../../marketing/enabled";
import { publicSite } from "../../product/public-site";
import { RESERVED_SEGMENTS } from "../../proxy-segments";

/**
 * The product's table of public addresses, compiled for this deployment
 * (ADR-080) — `null` where there is none to serve:
 *
 * - the product declares no table (Saas-Core itself, HoofCare, MedPlano);
 * - the profile shows the core's marketing on its platform host
 *   (`features.marketingSite` is not `false`): a host has one home page, and
 *   there it is the core's;
 * - the table cannot be served as written. That is caught where the table is
 *   built — `lib/product-site/slot.test.ts` runs in the product's gate — and
 *   here it only keeps a broken table from taking the panel down with it:
 *   the public pages are off, and the reason is in `productSiteProblem`.
 */
function compile(): { site: CompiledSite | null; problem: Error | null } {
  if (!publicSite || marketingSiteEnabled) return { site: null, problem: null };
  try {
    return {
      site: compileProductSite(publicSite, {
        locales: contentLocales,
        defaultLocale: routing.defaultLocale,
        reserved: RESERVED_SEGMENTS,
      }),
      problem: null,
    };
  } catch (error) {
    console.error(error);
    return { site: null, problem: error as Error };
  }
}

export const { site: productSite, problem: productSiteProblem } = compile();

/**
 * The address of one of the product's public pages in a language — the only
 * way a link to it is written. Throws for a page or a language the table has
 * not, so a wrong link fails where it is written, not where it is clicked.
 */
export function siteHref(
  route: string,
  locale: string,
  params?: SiteParams,
): string {
  if (!productSite) {
    throw new Error("This deployment serves no public pages of the product.");
  }
  return productSite.href(route, locale, params);
}
