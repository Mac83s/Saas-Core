import { siteUiTexts } from "@saas-core/site-blocks";

import {
  GONE_HOME_HEADER,
  GONE_LOCALE_HEADER,
} from "../../modules/shared/sites/gone-headers";

export const dynamic = "force-dynamic";

/**
 * The page of an address gone for good (ADR-077): 410, in the language the
 * address was asked in, with the way to that language's home. A route handler
 * because a page cannot answer 410; reached only through the proxy's rewrite,
 * which sets the two headers itself and refuses this path asked for directly.
 * Small on purpose: no menu, no look of the site — the address is not a page
 * of it any more.
 */
export function GET(request: Request): Response {
  const locale = request.headers.get(GONE_LOCALE_HEADER) || undefined;
  const homePath = request.headers.get(GONE_HOME_HEADER) || undefined;
  const texts = siteUiTexts(locale ?? "en");
  const home = homePath?.startsWith("/")
    ? `<p><a href="${escape(homePath)}">${escape(texts.notFound.home)}</a></p>`
    : "";
  const document = `<!doctype html>
<html lang="${escape(locale ?? "en")}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>${escape(texts.gone.title)}</title>
<style>
body{margin:0;font-family:system-ui,sans-serif;color:#1c1917;background:#fff}
main{max-width:36rem;margin:0 auto;padding:6rem 1.5rem;text-align:center}
h1{font-size:1.5rem;font-weight:600;margin:0 0 1rem}
p{margin:0 0 1rem;color:#57534e}
a{color:#1c1917;text-decoration:underline}
</style>
</head>
<body><main><h1>${escape(texts.gone.title)}</h1><p>${escape(texts.gone.body)}</p>${home}</main></body>
</html>`;
  return new Response(document, {
    status: 410,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "x-robots-tag": "noindex",
      "cache-control": "no-store",
    },
  });
}

function escape(value: string): string {
  return value.replace(
    /[&<>"']/g,
    (sign) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        sign
      ] ?? sign,
  );
}
