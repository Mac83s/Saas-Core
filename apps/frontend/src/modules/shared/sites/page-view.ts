/** The request method, carried across the proxy's rewrite: a page component
 *  can read the request headers but not the method, and a monitor's HEAD is
 *  not somebody reading the page. */
export const PUBLIC_SITE_METHOD_HEADER = "x-saas-core-site-method";

/** Tools, not people: crawlers (our own audit included), link previews,
 *  monitors, performance tests and scripts. Matched loosely on purpose — a
 *  person's browser names none of these. */
const NOT_A_PERSON =
  /bot|crawl|spider|slurp|preview|facebookexternalhit|embedly|whatsapp|telegram|discord|slack|skype|pinterest|monitor|uptime|pingdom|lighthouse|pagespeed|gtmetrix|headless|phantom|curl|wget|python|httpclient|http-client|go-http|java\/|okhttp|axios|node-fetch|undici|libwww|scrapy|validator/i;

type RequestHeaders = { get(name: string): string | null };

/** Whether this request is a person opening a published page (ADR-060).
 *
 *  Decided here, in the renderer, because only the renderer sees the visitor's
 *  request: the backend is told the answer and never the user agent, so the
 *  count carries nothing about who asked. Fetch metadata separates a document
 *  from a prefetch or a subresource; a browser too old to send it is still
 *  counted, because the alternative is losing real readers. */
export function countsAsPageView(headers: RequestHeaders): boolean {
  if (
    (headers.get(PUBLIC_SITE_METHOD_HEADER) ?? "GET").toUpperCase() !== "GET"
  ) {
    return false;
  }
  const purpose = `${headers.get("sec-purpose") ?? ""} ${headers.get("purpose") ?? ""}`;
  if (/prefetch|prerender/i.test(purpose)) return false;
  const destination = headers.get("sec-fetch-dest");
  if (destination !== null && destination !== "document") return false;
  const userAgent = headers.get("user-agent") ?? "";
  return userAgent.trim() !== "" && !NOT_A_PERSON.test(userAgent);
}
