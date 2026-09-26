import type { ReactNode } from "react";
import { headers } from "next/headers";

import "@saas-core/ui/globals.css";
import { countsAsPageView } from "../../modules/shared/sites/page-view";
import {
  getPublicSite,
  publicSitePath,
} from "../../modules/shared/sites/public-site";
import { PUBLIC_SITE_PATH_HEADER } from "../../proxy";

/** WCAG 2.2 requires the document to declare its language; without it a screen
 *  reader announces Polish copy with an English voice. The page below knows its
 *  locale but cannot set `<html>`, so the layout resolves it too — `getPublicSite`
 *  is wrapped in `cache()`, so this shares the page's fetch rather than adding
 *  one. A visitor reaching an unpublished address gets no page and no claim
 *  about its language, which is better than asserting the wrong one. */
export default async function PublicSiteLayout({
  children,
}: {
  children: ReactNode;
}) {
  const requestHeaders = await headers();
  const host = requestHeaders.get("host") ?? "";
  // Built like the page's own path, or the two calls would not be one — and
  // a visit could be counted twice.
  const path = publicSitePath(
    (requestHeaders.get(PUBLIC_SITE_PATH_HEADER) ?? "/")
      .split("/")
      .map(decodeSegment),
  );
  let locale: string | undefined;
  try {
    const result = await getPublicSite(
      host,
      path,
      countsAsPageView(requestHeaders),
    );
    if (result.kind === "page") locale = result.page.locale;
  } catch {
    // The page route reports the failure; the layout only loses the language.
  }

  return (
    <html lang={locale}>
      <body>{children}</body>
    </html>
  );
}

function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}
