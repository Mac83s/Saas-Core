import createMiddleware from "next-intl/middleware";
import { NextRequest, NextResponse } from "next/server";

import { routing } from "#i18n/routing";
import { deployment } from "./generated/deployment";
import { normalizeRequestHostname } from "./proxy-host";

const internationalization = createMiddleware(routing);

/** Carries the visitor-facing path across the rewrite into `/site-renderer`,
 *  so the public layout can set `<html lang>` from the published page. */
export const PUBLIC_SITE_PATH_HEADER = "x-saas-core-site-path";

export default function proxy(request: NextRequest) {
  const hostname = normalizeRequestHostname(request.headers.get("host"));
  if (!isControlHostname(hostname)) {
    const rewritten = request.nextUrl.clone();
    rewritten.pathname = `/site-renderer${request.nextUrl.pathname}`;
    // The rewritten path is what the layout sees, and a layout cannot read the
    // route params of the page below it — so the original path travels in a
    // header. Set, never appended: a visitor could otherwise supply their own
    // and steer which page's language the document claims.
    const forwarded = new Headers(request.headers);
    forwarded.set(PUBLIC_SITE_PATH_HEADER, request.nextUrl.pathname);
    return NextResponse.rewrite(rewritten, {
      request: { headers: forwarded },
    });
  }
  // The product's own sitemap and robots are app routes, not localized pages.
  if (METADATA_PATHS.has(request.nextUrl.pathname)) return NextResponse.next();
  if (
    !deployment.features.publicBooking &&
    bookingPathDisabled(request.nextUrl.pathname)
  ) {
    return new NextResponse(null, { status: 404 });
  }
  return internationalization(request);
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
    "/((?!api|healthz|site-renderer|_next|_vercel|.*\\..*).*)",
    // The dot exclusion above exists to let static assets through
    // untouched, but it also swallowed the two addresses a feed reader and
    // a crawler ask for by name. They are public-site paths and need the
    // same rewrite as any other page on that host.
    "/rss.xml",
    "/atom.xml",
    "/sitemap.xml",
    "/robots.txt",
  ],
};
