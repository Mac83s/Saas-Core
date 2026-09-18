import { describe, expect, it } from "vitest";

import { deployment } from "../generated/deployment";
import { localizedUrl, marketingMetadata } from "./seo";

const origin = `https://${deployment.product.platformDomain}`;

describe("marketing SEO", () => {
  it("puts Polish at the root and English under /en", () => {
    expect(localizedUrl("pl", "/")).toBe(`${origin}/`);
    expect(localizedUrl("en", "/")).toBe(`${origin}/en`);
    expect(localizedUrl("en", "/pricing")).toBe(`${origin}/en/pricing`);
  });

  it("links both languages and x-default from every page", () => {
    const meta = marketingMetadata({ locale: "en", path: "/pricing", title: "t", description: "d" });
    expect(meta.alternates?.canonical).toBe(`${origin}/en/pricing`);
    expect(meta.alternates?.languages).toEqual({
      pl: `${origin}/pricing`,
      en: `${origin}/en/pricing`,
      "x-default": `${origin}/pricing`,
    });
  });
});
