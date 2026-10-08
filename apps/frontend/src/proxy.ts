import createMiddleware from "next-intl/middleware";
import { defineRouting } from "next-intl/routing";
import { NextRequest, NextResponse } from "next/server";

import { isPanelLocale, panelLocales, routing } from "#i18n/routing";
import { deployment } from "./generated/deployment";
import { marketingSiteEnabled } from "./marketing/enabled";
import { PUBLIC_SITE_METHOD_HEADER } from "./modules/shared/sites/page-view";
import {
  oldAddressAnswer,
  sitePageAnswer,
  spellingAnswer,
  untouchedAnswer,
} from "./lib/product-site/answers";
import { absoluteUrl, normalizeRequestHostname } from "./proxy-host";
import { GUEST_SEGMENTS, PANEL_SEGMENTS } from "./proxy-segments";

/**
 * Two route groups (TL17). The team's pages speak pl/en and may follow the
 * person's cookie or browser; the guest pages speak every content language,
 * and only by their address — no detection, no `NEXT_LOCALE` cookie, no Link
 * header — so a crawler and a visitor get the same page for the same URL.
 */
const PANEL_DEFAULT_LOCALE = "pl";
const panelInternationalization = createMiddleware(
  defineRouting({
    locales: [...panelLocales],
    defaultLocale: PANEL_DEFAULT_LOCALE,
    localePrefix: "as-needed",
  }),
);
const publicInternationalization = createMiddleware(
  defineRouting({
    ...routing,
    localeDetection: false,
    localeCookie: false,
    alternateLinks: false,
  }),
);

/** Carries the visitor-facing path across the rewrite into `/site-renderer`,
 *  so the public layout can set `<html lang>` from the published page. */
export const PUBLIC_SITE_PATH_HEADER = "x-saas-core-site-path";
/** Whether the visitor's path ended with a slash. Route params drop it, and a
 *  customer site's canonical addresses keep it (ADR-071), so the backend has
 *  to hear the path as typed to answer the other spelling with one 308. */
export const PUBLIC_SITE_TRAILING_SLASH_HEADER =
  "x-saas-core-site-trailing-slash";

export default function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  // The renderer is reachable only through the rewrite below, which sets the
  // headers it trusts. Asked for directly, with headers of the visitor's own
  // choosing, it would render any site under any address.
  if (pathname === "/site-renderer" || pathname.startsWith("/site-renderer/")) {
    return new NextResponse(null, { status: 404 });
  }
  // An address the matcher lets in only for the folder of a product's page
  // files (ADR-080), where no product declares any: as if it had not.
  const untouched = untouchedAnswer(request);
  if (untouched) return untouched;
  const hostname = normalizeRequestHostname(request.headers.get("host"));
  if (!isControlHostname(hostname)) {
    const rewritten = request.nextUrl.clone();
    rewritten.pathname = `/site-renderer${request.nextUrl.pathname}`;
    // The rewritten path is what the layout sees, and a layout cannot read the
    // route params of the page below it — so the original path travels in a
    // header. Set, never appended: a visitor could otherwise supply their own
    // and steer which page's language the document claims.
    const forwarded = new Headers(request.headers);
    forwarded.set(PUBLIC_SITE_PATH_HEADER, pathname);
    forwarded.set(
      PUBLIC_SITE_TRAILING_SLASH_HEADER,
      pathname.length > 1 && pathname.endsWith("/") ? "1" : "0",
    );
    // Same rule for the method, which decides whether this is a page view.
    forwarded.set(PUBLIC_SITE_METHOD_HEADER, request.method);
    return NextResponse.rewrite(rewritten, {
      request: { headers: forwarded },
    });
  }
  // An address of the site a product's public pages replaced (ADR-080): one
  // 308 or a 410, before anything below spells the address canonically —
  // and a product page that needs two corrections gets both in one 308.
  const old = oldAddressAnswer(request) ?? spellingAnswer(request);
  if (old) return old;
  // The platform's own pages have no trailing slash; the other spelling is one
  // 308 away, as Next did before customer sites needed the slash kept. Next
  // wants an absolute Location from a proxy; built from the visitor's own host
  // and the scheme the gateway saw, so it stays on their port.
  if (pathname.length > 1 && pathname.endsWith("/")) {
    return NextResponse.redirect(
      absoluteUrl(
        request,
        `${pathname.replace(/\/+$/, "")}${request.nextUrl.search}`,
      ),
      308,
    );
  }
  // The product's own sitemap and robots are app routes, not localized pages.
  if (METADATA_PATHS.has(pathname)) return NextResponse.next();
  if (
    !deployment.features.publicBooking &&
    bookingPathDisabled(request.nextUrl.pathname)
  ) {
    return new NextResponse(null, { status: 404 });
  }
  // A product's own public page, or its 404 (ADR-080). Nothing where the
  // product declares none: the lines below are then all there is.
  const page = sitePageAnswer(request);
  if (page) return page;
  if (!marketingSiteEnabled) {
    // A deployment that shows no marketing of the core on its platform host
    // (`features.marketingSite: false`): the front door is sign-in, and the
    // core's marketing pages and catalogue are not here.
    const [first = "", ...rest] = pathname.split("/").slice(1);
    const prefixed = (routing.locales as readonly string[]).includes(first);
    const segment = prefixed ? (rest[0] ?? "") : first;
    if (segment === "") {
      // Temporary: the profile may switch the marketing back on.
      return NextResponse.redirect(
        absoluteUrl(request, signInPath(prefixed ? first : undefined)),
        307,
      );
    }
    if (!PANEL_SEGMENTS.has(segment) && !GUEST_SEGMENTS.has(segment)) {
      return new NextResponse(null, { status: 404 });
    }
  }
  return localized(request, pathname);
}

/** Sign-in in the panel's language nearest to the address asked for. */
function signInPath(prefix: string | undefined): string {
  if (!prefix || prefix === PANEL_DEFAULT_LOCALE) return "/login";
  return isPanelLocale(prefix) ? `/${prefix}/login` : "/en/login";
}

/**
 * Hands a platform page to its group's locale middleware. A redirect that
 * only spells the address canonically is permanent (308); one that follows
 * the person's cookie or browser stays temporary (307) — a cached 308 would
 * keep sending someone who later switched language back to the old one.
 */
function localized(request: NextRequest, pathname: string): Response {
  const [first = "", ...rest] = pathname.split("/").slice(1);
  const prefixed = (routing.locales as readonly string[]).includes(first);
  const segment = prefixed ? (rest[0] ?? "") : first;
  if (!PANEL_SEGMENTS.has(segment)) {
    // No detection here, so every redirect is canonical.
    return permanent(publicInternationalization(request));
  }
  if (prefixed && !isPanelLocale(first)) {
    // A guest language in front of the team's page: the panel's English.
    return NextResponse.redirect(
      absoluteUrl(request, `/en/${rest.join("/")}${request.nextUrl.search}`),
      308,
    );
  }
  const response = panelInternationalization(request);
  // With a language in the address the redirect only drops the default
  // prefix; without one it came from detection.
  return prefixed ? permanent(response) : response;
}

function permanent(response: Response): Response {
  const location = response.headers.get("location");
  if (response.status !== 307 || !location) return response;
  const moved = NextResponse.redirect(location, 308);
  response.headers.forEach((value, key) => {
    if (key !== "location" && key !== "set-cookie")
      moved.headers.set(key, value);
  });
  for (const cookie of response.headers.getSetCookie()) {
    moved.headers.append("set-cookie", cookie);
  }
  return moved;
}

const METADATA_PATHS = new Set(["/sitemap.xml", "/robots.txt"]);

function bookingPathDisabled(pathname: string): boolean {
  return (
    pathname.includes("/book/") ||
    pathname.includes("/booking/") ||
    pathname.endsWith("/panel/calendar") ||
    pathname.includes("/panel/calendar/")
  );
}

function isControlHostname(hostname: string): boolean {
  const configured = (process.env.FRONTEND_CONTROL_HOSTS ?? "")
    .split(",")
    .map((value) => value.trim().toLowerCase().replace(/\.$/, ""))
    .filter(Boolean);
  return new Set([
    "localhost",
    "127.0.0.1",
    deployment.product.platformDomain.toLowerCase(),
    ...configured,
  ]).has(hostname);
}

export const config = {
  matcher: [
    // `/site-renderer` is matched on purpose: the proxy refuses it.
    "/((?!api|healthz|_next|_vercel|.*\\..*).*)",
    // The dot exclusion above exists to let static assets through
    // untouched, but it also swallowed the two addresses a feed reader and
    // a crawler ask for by name. They are public-site paths and need the
    // same rewrite as any other page on that host.
    "/rss.xml",
    "/atom.xml",
    // A language's own feeds (TL14).
    "/:locale/rss.xml",
    "/:locale/atom.xml",
    // What a language model reads first about a site, per language (TL19).
    "/llms.txt",
    "/:locale/llms.txt",
    "/sitemap.xml",
    "/robots.txt",
    // The folder of a product's page files (ADR-080), dots included: an
    // address with a dot would otherwise reach a page file there without
    // passing the product's table. Where no product declares a table the
    // proxy lets these through untouched (`untouchedAnswer`).
    "/product-site/:path*",
  ],
};
