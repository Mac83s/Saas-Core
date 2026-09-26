import { describe, expect, it } from "vitest";

import { countsAsPageView, PUBLIC_SITE_METHOD_HEADER } from "./page-view";

const BROWSER =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36";

function request(values: Record<string, string>) {
  const headers = new Headers({
    [PUBLIC_SITE_METHOD_HEADER]: "GET",
    "user-agent": BROWSER,
    "sec-fetch-dest": "document",
    ...values,
  });
  return headers;
}

describe("countsAsPageView", () => {
  it("counts a person's browser opening a page", () => {
    expect(countsAsPageView(request({}))).toBe(true);
  });

  it("counts a browser that sends no fetch metadata", () => {
    const headers = request({});
    headers.delete("sec-fetch-dest");
    expect(countsAsPageView(headers)).toBe(true);
  });

  it.each([
    ["a HEAD from a monitor", { [PUBLIC_SITE_METHOD_HEADER]: "HEAD" }],
    ["a speculative prefetch", { "sec-purpose": "prefetch" }],
    ["a prerender", { "sec-purpose": "prefetch;prerender" }],
    ["a legacy prefetch", { purpose: "prefetch" }],
    ["a subresource", { "sec-fetch-dest": "image" }],
    ["no user agent", { "user-agent": "" }],
    [
      "a search crawler",
      { "user-agent": "Mozilla/5.0 (compatible; Googlebot/2.1)" },
    ],
    ["our own audit", { "user-agent": "SEOSiteAuditBot" }],
    ["a link preview", { "user-agent": "facebookexternalhit/1.1" }],
    ["a headless browser", { "user-agent": `${BROWSER} HeadlessChrome/140.0` }],
    ["a performance test", { "user-agent": `${BROWSER} Chrome-Lighthouse` }],
    ["a script", { "user-agent": "python-requests/2.32" }],
  ])("does not count %s", (_label, values) => {
    expect(countsAsPageView(request(values))).toBe(false);
  });
});
