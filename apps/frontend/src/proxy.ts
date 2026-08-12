import createMiddleware from "next-intl/middleware";
import { NextRequest, NextResponse } from "next/server";

import { routing } from "#i18n/routing";
import { deployment } from "./generated/deployment";
import { normalizeRequestHostname } from "./proxy-host";

const internationalization = createMiddleware(routing);

export default function proxy(request: NextRequest) {
  const hostname = normalizeRequestHostname(request.headers.get("host"));
  if (!isControlHostname(hostname)) {
    const rewritten = request.nextUrl.clone();
    rewritten.pathname = `/site-renderer${request.nextUrl.pathname}`;
    return NextResponse.rewrite(rewritten);
  }
  if (
    !deployment.features.publicBooking &&
    bookingPathDisabled(request.nextUrl.pathname)
  ) {
    return new NextResponse(null, { status: 404 });
  }
  return internationalization(request);
}

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
  matcher: "/((?!api|healthz|site-renderer|_next|_vercel|.*\\..*).*)",
};
