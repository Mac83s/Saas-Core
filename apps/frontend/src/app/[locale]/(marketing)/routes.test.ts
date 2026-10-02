import { describe, expect, it, vi } from "vitest";

import UnknownAddress from "./[...rest]/page";
import * as productPage from "./[slug]/page";

vi.mock("#i18n/navigation", () => ({ Link: "a" }));

describe("marketing routes", () => {
  it("render product pages per request", () => {
    // An empty list from it (a profile without product pages) made every slug
    // an on-demand static render, and the site header reads the locale from
    // the request: unknown addresses answered 500 instead of 404.
    expect("generateStaticParams" in productPage).toBe(false);
  });

  it("answer 404 for an address no route claims", () => {
    let thrown: unknown;
    try {
      UnknownAddress();
    } catch (error) {
      thrown = error;
    }
    expect(thrown).toMatchObject({ digest: "NEXT_HTTP_ERROR_FALLBACK;404" });
  });
});
