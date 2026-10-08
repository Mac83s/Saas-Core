import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  fixtureDeployment,
  fixtureOldAddresses,
  fixtureSite,
  fixtureSitemap,
} from "./fixture";

const origin = "https://platform.example.test";

async function load(deployment = fixtureDeployment()) {
  vi.resetModules();
  vi.doMock("../../generated/deployment", () => ({ deployment }));
  vi.doMock("../../product", () => ({ product: {} }));
  vi.doMock("../../product/public-site", () => ({ publicSite: fixtureSite }));
  vi.doMock("../../product/old-addresses", () => ({
    oldAddresses: fixtureOldAddresses,
  }));
  vi.doMock("../../product/site-sitemap", () => ({
    siteSitemap: async () => fixtureSitemap,
  }));
  vi.doMock("../../modules/shared/profiles/catalog-server", () => ({
    readCatalogLocalesOnServer: async () => null,
    readCatalogSitemapOnServer: async () => null,
  }));
  const { default: sitemap } = await import("../../app/sitemap");
  const { default: robots } = await import("../../app/robots");
  const { default: proxy } = await import("../../proxy");
  return { sitemap, robots, proxy, seo: await import("./seo") };
}

beforeEach(() => {
  // The fixture names one page the table has not; the sitemap says so.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  for (const mocked of [
    "../../generated/deployment",
    "../../product",
    "../../product/public-site",
    "../../product/old-addresses",
    "../../product/site-sitemap",
    "../../modules/shared/profiles/catalog-server",
  ]) {
    vi.doUnmock(mocked);
  }
  vi.resetModules();
});

describe("a product's public pages in the sitemap (ADR-080)", () => {
  it("lists each page once per language it exists in, with all of them named", async () => {
    const { sitemap } = await load();

    const lines = await sitemap();
    const urls = lines.map((line) => line.url);

    expect(urls).toEqual([
      `${origin}/`,
      `${origin}/en`,
      `${origin}/de`,
      `${origin}/es`,
      `${origin}/ru`,
      `${origin}/rasy-psow`,
      `${origin}/en/dog-breeds`,
      `${origin}/de/hunderassen`,
      `${origin}/quiz`,
      `${origin}/en/quiz`,
      `${origin}/de/quiz`,
      `${origin}/es/quiz`,
      `${origin}/ru/quiz`,
      `${origin}/rasy-psow/owczarek-niemiecki`,
      `${origin}/en/dog-breeds/german-shepherd`,
      `${origin}/de/hunderassen/deutscher-schaeferhund`,
      `${origin}/poradnik/zywienie`,
    ]);
    const translated = lines.find(
      (line) => line.url === `${origin}/en/dog-breeds/german-shepherd`,
    );
    expect(translated?.alternates?.languages).toEqual({
      pl: `${origin}/rasy-psow/owczarek-niemiecki`,
      en: `${origin}/en/dog-breeds/german-shepherd`,
      de: `${origin}/de/hunderassen/deutscher-schaeferhund`,
      "x-default": `${origin}/rasy-psow/owczarek-niemiecki`,
    });
    expect(translated?.lastModified).toBe("2026-10-08T08:00:00Z");
  });

  it("lists nothing that is redirected or gone", async () => {
    const { sitemap } = await load();

    const urls = (await sitemap()).map((line) => line.url);

    // The product still names the renamed entry; the rule over it wins.
    expect(urls).not.toContain(`${origin}/rasy-psow/owczarek`);
    for (const source of [
      ...Object.keys(fixtureOldAddresses.moved!),
      ...fixtureOldAddresses.gone!,
    ]) {
      expect(urls, source).not.toContain(`${origin}${source}`);
    }
  });

  it("leaves out a page the table has not, and still answers", async () => {
    const { sitemap } = await load();

    const urls = (await sitemap()).map((line) => line.url);

    expect(urls.some((url) => url.includes("shop"))).toBe(false);
    expect(urls.length).toBe(17);
    expect(console.error).toHaveBeenCalledWith(
      expect.stringContaining('the sitemap names "/shop"'),
    );
  });

  it("lists only addresses the proxy answers with a page", async () => {
    const { sitemap, proxy } = await load();
    const { NextRequest } = await import("next/server");

    for (const line of await sitemap()) {
      const address = line.url.slice(origin.length) || "/";
      const response = await proxy(
        new NextRequest(`http://localhost${address}`, {
          headers: { host: "localhost:8080" },
        }),
      );
      const rewrite = response.headers.get("x-middleware-rewrite") ?? "";
      expect(response.status, address).toBe(200);
      expect(rewrite, address).toContain("/product-site");
      expect(rewrite, address).not.toContain("_unclaimed");
    }
  });

  it("keeps robots as it was: the panel closed, the sitemap named", async () => {
    const { robots } = await load();

    const said = robots();

    expect(said.sitemap).toBe(`${origin}/sitemap.xml`);
    expect(said.rules).toMatchObject({ allow: "/" });
    const closed = (said.rules as { disallow: string[] }).disallow;
    expect(closed).toContain("/panel");
    expect(closed).toContain("/ru/panel");
    expect(closed).toContain("/api/");
  });

  it("is the core's sitemap alone where the profile shows the core's marketing", async () => {
    const { sitemap } = await load({
      ...fixtureDeployment({}, ["pl", "en"]),
      features: { publicBooking: true },
    } as ReturnType<typeof fixtureDeployment>);

    const urls = (await sitemap()).map((line) => line.url);

    expect(urls).toContain(`${origin}/pricing`);
    expect(urls.some((url) => url.includes("rasy-psow"))).toBe(false);
  });
});

describe("a public page's canonical and hreflang (ADR-080)", () => {
  it("come from the table, with each language's own name of the page", async () => {
    const { seo } = await load();

    const metadata = seo.siteMetadata({
      route: "/breeds/[slug]",
      locale: "en",
      params: {
        pl: { slug: "owczarek-niemiecki" },
        en: { slug: "german-shepherd" },
      },
      title: "German Shepherd",
      description: "The breed.",
    });

    expect(metadata.alternates).toEqual({
      canonical: `${origin}/en/dog-breeds/german-shepherd`,
      languages: {
        pl: `${origin}/rasy-psow/owczarek-niemiecki`,
        en: `${origin}/en/dog-breeds/german-shepherd`,
        "x-default": `${origin}/rasy-psow/owczarek-niemiecki`,
      },
    });
    expect(metadata.openGraph).toMatchObject({
      url: `${origin}/en/dog-breeds/german-shepherd`,
      locale: "en_GB",
    });
  });

  it("name x-default by the first language where the default has no page", async () => {
    const { seo } = await load();

    const alternates = seo.siteAlternates({
      route: "/breeds/[slug]",
      locale: "de",
      params: { en: { slug: "a" }, de: { slug: "b" } },
    });

    expect(alternates.languages["x-default"]).toBe(`${origin}/en/dog-breeds/a`);
    expect(alternates.canonical).toBe(`${origin}/de/hunderassen/b`);
  });

  it("leave out a language whose address an old-address rule answers, as the sitemap does", async () => {
    const { seo } = await load();
    // The Polish name of this entry was renamed: `/rasy-psow/owczarek` is a
    // rule now, and no page head or language switch may still name it.
    const params = {
      pl: { slug: "owczarek" },
      en: { slug: "german-shepherd" },
    };

    expect(seo.siteVersions("/breeds/[slug]", params)).toEqual([
      { locale: "en", path: "/en/dog-breeds/german-shepherd" },
    ]);
    expect(
      seo.siteAlternates({ route: "/breeds/[slug]", locale: "en", params })
        .languages,
    ).toEqual({
      en: `${origin}/en/dog-breeds/german-shepherd`,
      "x-default": `${origin}/en/dog-breeds/german-shepherd`,
    });
    expect(
      seo
        .siteVersions("/breeds/[slug]", { slug: "labrador" })
        .map((version) => version.locale),
    ).toEqual(["pl", "en", "de"]);
  });

  it("refuse a page in a language it has no address in", async () => {
    const { seo } = await load();

    expect(() =>
      seo.siteAlternates({ route: "/breeds", locale: "es" }),
    ).toThrow(/no address in es/);
  });
});
