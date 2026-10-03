import { beforeEach, describe, expect, it, vi } from "vitest";

const server = vi.hoisted(() => ({
  readCatalogLocalesOnServer: vi.fn(),
  readCatalogSitemapOnServer: vi.fn(),
}));

// The reads are server-only; the sitemap's choices are what is tested here.
vi.mock("../modules/shared/profiles/catalog-server", () => server);
vi.mock("../marketing/content", async (original) => ({
  ...(await original<typeof import("../marketing/content")>()),
  productHasCatalog: true,
}));

import { deployment } from "../generated/deployment";
import sitemap from "./sitemap";

const origin = `https://${deployment.product.platformDomain}`;

beforeEach(() => {
  vi.clearAllMocks();
});

describe("platform sitemap (TL20)", () => {
  it("lists a card in each language it is whole in, and only there", async () => {
    server.readCatalogLocalesOnServer.mockResolvedValue(["pl", "en"]);
    server.readCatalogSitemapOnServer.mockResolvedValue([
      {
        city_slug: "mragowo",
        slug: "salon",
        source_locale: "pl",
        translated_locales: ["en", "de"],
        updated_at: "2026-10-03T08:00:00Z",
      },
      {
        city_slug: "olsztyn",
        slug: "warsztat",
        source_locale: "pl",
        translated_locales: [],
        updated_at: "2026-10-02T08:00:00Z",
      },
    ]);

    const urls = (await sitemap()).map((entry) => entry.url);
    const translated = (await sitemap()).find(
      (entry) => entry.url === `${origin}/en/katalog/mragowo/salon`,
    );

    expect(urls).toContain(`${origin}/katalog/mragowo/salon`);
    expect(urls).toContain(`${origin}/en/katalog/mragowo/salon`);
    expect(urls).toContain(`${origin}/katalog/olsztyn/warsztat`);
    expect(urls).not.toContain(`${origin}/en/katalog/olsztyn/warsztat`);
    // `de` is not routed yet: not a URL, not an alternate.
    expect(urls.some((url) => url.includes("/de/"))).toBe(false);
    expect(translated?.alternates?.languages).toEqual({
      pl: `${origin}/katalog/mragowo/salon`,
      en: `${origin}/en/katalog/mragowo/salon`,
      "x-default": `${origin}/katalog/mragowo/salon`,
    });
    expect(translated?.lastModified).toBe("2026-10-03T08:00:00Z");
    expect(urls).toContain(`${origin}/en/katalog`);
  });

  it("a listing language no card speaks stays out", async () => {
    server.readCatalogLocalesOnServer.mockResolvedValue(["pl"]);
    server.readCatalogSitemapOnServer.mockResolvedValue([]);

    const urls = (await sitemap()).map((entry) => entry.url);

    expect(urls).toContain(`${origin}/katalog`);
    expect(urls).not.toContain(`${origin}/en/katalog`);
  });

  it("without the backend the product's pages and the listing are still there", async () => {
    // Both reads answer null when the backend does not answer.
    server.readCatalogLocalesOnServer.mockResolvedValue(null);
    server.readCatalogSitemapOnServer.mockResolvedValue(null);

    const urls = (await sitemap()).map((entry) => entry.url);

    expect(urls).toContain(`${origin}/`);
    expect(urls).toContain(`${origin}/en/pricing`);
    expect(urls).toContain(`${origin}/katalog`);
    expect(urls.some((url) => url.includes("/katalog/"))).toBe(false);
  });
});
