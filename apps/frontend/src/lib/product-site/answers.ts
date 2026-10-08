import { NextRequest, NextResponse } from "next/server";

import { routing } from "#i18n/routing";
import {
  SITE_PAGES_SEGMENT,
  SITE_UNCLAIMED_PATH,
} from "#lib/product-site/table";
import { absoluteUrl } from "../../proxy-host";
import { RESERVED_SEGMENTS } from "../../proxy-segments";
import { goneDocument } from "./gone-page";
import { productOldAddresses } from "./old-addresses";
import { productSite, productSiteDeclared } from "./site";

/**
 * What the proxy answers for a product's public pages on the platform host
 * (ADR-080). Both functions answer `null` — "not mine, go on as before" —
 * for every address of a deployment whose product declares no pages, so
 * such a deployment's requests take the path they always took.
 */

/** next-intl reads a request's language from this header; its own
 *  middleware sets it, and so does the rewrite below, which stands in for
 *  it. `answers.test.ts` holds the name against the real middleware. */
export const LOCALE_HEADER = "X-NEXT-INTL-LOCALE";

/**
 * An address of the site these pages replaced: one 308 straight to where it
 * moved, or 410. Asked before anything spells the address canonically — a
 * trailing slash or a language prefix on an old address must not cost the
 * visitor a second redirect — and only on the platform host: the proxy has
 * handed a customer's site to its renderer before it gets here.
 */
export function oldAddressAnswer(request: NextRequest): Response | null {
  const rule = productOldAddresses?.lookup(request.nextUrl.pathname);
  if (!rule) return null;
  if (rule.kind === "moved") {
    return NextResponse.redirect(
      absoluteUrl(request, `${rule.to}${request.nextUrl.search}`),
      308,
    );
  }
  const home = productSite?.routes.includes("/")
    ? productSite
        .versions("/")
        .find((version) => version.locale === rule.locale)
    : undefined;
  return new NextResponse(goneDocument(rule.locale, home?.path ?? null), {
    status: 410,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "x-robots-tag": "noindex",
      "cache-control": "no-store",
    },
  });
}

/**
 * A product page asked for under the default language's prefix *and* with a
 * trailing slash: one 308 to its address, not one per correction. Any other
 * address keeps the proxy's own slash rule.
 */
export function spellingAnswer(request: NextRequest): Response | null {
  const { pathname } = request.nextUrl;
  if (!productSite || pathname.length < 2 || !pathname.endsWith("/")) {
    return null;
  }
  const match = productSite.match(pathname.replace(/\/+$/, ""));
  if (match?.kind !== "canonical") return null;
  return NextResponse.redirect(
    absoluteUrl(request, `${match.path}${request.nextUrl.search}`),
    308,
  );
}

/** The addresses with a dot the proxy has always been handed: feeds, the
 *  language models' file, the sitemap and robots. */
const DOTTED_BEFORE =
  /^\/(?:[^/]+\/)?(?:rss\.xml|atom\.xml|llms\.txt)$|^\/(?:sitemap\.xml|robots\.txt)$/;

/**
 * The proxy's matcher lets every address under the folder of a product's
 * page files in, dots included — otherwise `/en/product-site/x/a.b` would
 * reach a page file without passing the table. Where no product declares a
 * table that folder holds nothing, and such an address goes on untouched,
 * exactly as it did before the matcher knew the folder.
 */
export function untouchedAnswer(request: NextRequest): Response | null {
  const { pathname } = request.nextUrl;
  if (productSiteDeclared) return null;
  if (!pathname.includes(".") || DOTTED_BEFORE.test(pathname)) return null;
  return NextResponse.next();
}

/** A path segment as the router will read it. */
function decoded(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/**
 * The product's page for an address, or its own 404 for one nobody claims.
 * `null` for the team's, a guest's and the platform's own addresses, and for
 * `/` while the product has no home page (the front door stays sign-in) —
 * and for everything but the folder of its page files where the product
 * declares a table this profile does not serve.
 */
export function sitePageAnswer(request: NextRequest): Response | null {
  if (!productSiteDeclared) return null;
  const { pathname } = request.nextUrl;
  const [first = "", second = ""] = pathname.split("/").slice(1);
  const prefixed = (routing.locales as readonly string[]).includes(first);
  const segment = prefixed ? second : first;
  // The folder of the product's page files is never an address, in any
  // spelling the router would read as its name — also where this profile
  // does not serve the table (the core's marketing is on): the files are in
  // the build all the same, and the locale middleware would hand a visitor
  // straight to them.
  if (decoded(segment) === SITE_PAGES_SEGMENT) {
    return new NextResponse(null, { status: 404 });
  }
  const site = productSite;
  if (!site) return null;
  if (RESERVED_SEGMENTS.exact.has(segment)) return null;

  const match = site.match(pathname);
  if (match?.kind === "canonical") {
    return NextResponse.redirect(
      absoluteUrl(request, `${match.path}${request.nextUrl.search}`),
      308,
    );
  }
  if (match) return pageOf(request, match.locale, match.page);
  if (segment === "" && !site.routes.includes("/")) return null;
  // Not an address of the table, in any spelling: the product's own 404, in
  // the language the address was asked in.
  return pageOf(
    request,
    prefixed ? first : site.defaultLocale,
    SITE_UNCLAIMED_PATH,
  );
}

/** Hands the visit to a page file of the product, in a language. */
function pageOf(request: NextRequest, locale: string, page: string): Response {
  const rewritten = request.nextUrl.clone();
  rewritten.pathname = `/${locale}/${SITE_PAGES_SEGMENT}${page === "/" ? "" : page}`;
  // Set, never appended: the visitor's own header must not name the language.
  const forwarded = new Headers(request.headers);
  forwarded.set(LOCALE_HEADER, locale);
  return NextResponse.rewrite(rewritten, { request: { headers: forwarded } });
}
