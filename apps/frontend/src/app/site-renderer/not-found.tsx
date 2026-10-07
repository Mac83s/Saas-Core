import { headers } from "next/headers";

import { siteUiTexts } from "@saas-core/site-blocks";

import { countsAsPageView } from "../../modules/shared/sites/page-view";
import {
  getPublicSite,
  publicSitePath,
} from "../../modules/shared/sites/public-site";
import {
  PUBLIC_SITE_PATH_HEADER,
  PUBLIC_SITE_TRAILING_SLASH_HEADER,
} from "../../proxy";

/** A company site's missing page, in the language the address was asked in,
 *  with the way to that language's home (TL14). An unknown host says nothing
 *  about any site and reads English. */
export default async function PublicSiteNotFound() {
  const requestHeaders = await headers();
  const path = publicSitePath(
    (requestHeaders.get(PUBLIC_SITE_PATH_HEADER) ?? "/")
      .split("/")
      .map(decodeSegment),
    requestHeaders.get(PUBLIC_SITE_TRAILING_SLASH_HEADER) === "1",
  );
  let locale: string | undefined;
  let homePath: string | undefined;
  let gone = false;
  try {
    // The page's own call, shared through `cache()`, so no second request.
    const result = await getPublicSite(
      requestHeaders.get("host") ?? "",
      path,
      countsAsPageView(requestHeaders),
    );
    if (result.kind === "not-found") {
      locale = result.locale;
      homePath = result.homePath;
      gone = result.gone === true;
    }
  } catch {
    // The missing page still says so.
  }
  const all = siteUiTexts(locale ?? "en");
  // An address gone for good is answered 410 by the proxy (ADR-077); when
  // the proxy had no verdict in time, this page says the same words.
  const texts = { ...all.notFound, ...(gone ? all.gone : {}) };
  return (
    <main className="mx-auto max-w-xl space-y-4 px-6 py-24 text-center">
      <h1 className="text-2xl font-semibold">{texts.title}</h1>
      <p className="text-muted-foreground">{texts.body}</p>
      {homePath ? (
        <p>
          <a className="text-primary underline" href={homePath}>
            {texts.home}
          </a>
        </p>
      ) : null}
    </main>
  );
}

function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}
