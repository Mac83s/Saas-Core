import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fixtureDeployment, fixtureOldAddresses, fixtureSite } from "./fixture";

/**
 * The platform's published content read by a product's pages (ADR-079 pkt
 * 30–32), with the test-only product of the product-site tests: its section
 * `/breeds` stands for a content type shown under a name per language.
 * What is held here is the product's half of the contract — the calls, what
 * comes back, and how address parts become addresses through its table.
 */
const origin = "https://platform.example.test";
const fetched = vi.fn();
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });

async function load() {
  vi.resetModules();
  vi.doMock("../../generated/deployment", () => ({
    deployment: fixtureDeployment(),
  }));
  vi.doMock("../../product", () => ({ product: {} }));
  vi.doMock("../../product/public-site", () => ({ publicSite: fixtureSite }));
  vi.doMock("../../product/old-addresses", () => ({
    oldAddresses: fixtureOldAddresses,
  }));
  return {
    content: await import("./content"),
    seo: await import("./seo"),
    site: await import("./site"),
    rules: (await import("./old-addresses")).productOldAddresses,
  };
}

const asked = (call = 0) => String(fetched.mock.calls[call]![0]);

const entry = {
  type: "breeds",
  locale: "en",
  slug: "german-shepherd",
  title: "German Shepherd",
  excerpt: "A working dog.",
  versions: [
    { locale: "pl", slug: "owczarek-niemiecki" },
    { locale: "en", slug: "german-shepherd" },
    { locale: "de", slug: "deutscher-schaeferhund" },
  ],
};

beforeEach(() => {
  fetched.mockReset();
  vi.stubGlobal("fetch", fetched);
});

afterEach(() => {
  vi.unstubAllGlobals();
  for (const mocked of [
    "../../generated/deployment",
    "../../product",
    "../../product/public-site",
    "../../product/old-addresses",
  ]) {
    vi.doUnmock(mocked);
  }
  vi.resetModules();
});

describe("a product's page reads an entry (ADR-079)", () => {
  it("asks by type, language and slug, on the server, uncached", async () => {
    const { content } = await load();
    fetched.mockResolvedValue(json({ entry, moved: null }));

    const result = await content.contentEntry({
      type: "breeds",
      locale: "en",
      slug: "german-shepherd",
    });

    expect(asked()).toBe(
      "http://127.0.0.1:8000/api/v1/public/content/types/breeds/entries/en/german-shepherd/",
    );
    expect(fetched.mock.calls[0]![1]).toEqual({ cache: "no-store" });
    expect(result).toEqual({ kind: "entry", entry });
  });

  it("is cached only for as long as the page says", async () => {
    const { content } = await load();
    fetched.mockImplementation(async () => json({ entry, moved: null }));

    await content.contentEntry({
      type: "breeds",
      locale: "en",
      slug: "german-shepherd",
      revalidate: 300,
    });
    await content.contentEntries({ type: "breeds", locale: "en" });
    await content.contentTypes({ revalidate: 60 });

    expect(fetched.mock.calls.map((call) => call[1])).toEqual([
      { next: { revalidate: 300 } },
      { cache: "no-store" },
      { next: { revalidate: 60 } },
    ]);
  });

  it("sends the address it gives the entry when it wants the JSON-LD nodes", async () => {
    const { content, seo } = await load();
    fetched.mockResolvedValue(json({ entry, moved: null }));
    const { canonical } = seo.siteAlternates({
      route: "/breeds/[slug]",
      locale: "en",
      params: { slug: "german-shepherd" },
    });

    await content.contentEntry({
      type: "breeds",
      locale: "en",
      slug: "german-shepherd",
      canonicalUrl: canonical,
    });

    expect(canonical).toBe(`${origin}/en/dog-breeds/german-shepherd`);
    expect(new URL(asked()).searchParams.get("canonical_url")).toBe(canonical);
  });

  it("turns the entry's versions into hreflang and a language switch through its table", async () => {
    const { content, seo } = await load();
    const params = content.contentVersions(entry.versions);

    expect(params).toEqual({
      pl: { slug: "owczarek-niemiecki" },
      en: { slug: "german-shepherd" },
      de: { slug: "deutscher-schaeferhund" },
    });
    expect(seo.siteVersions("/breeds/[slug]", params)).toEqual([
      { locale: "pl", path: "/rasy-psow/owczarek-niemiecki" },
      { locale: "en", path: "/en/dog-breeds/german-shepherd" },
      { locale: "de", path: "/de/hunderassen/deutscher-schaeferhund" },
    ]);
    const metadata = seo.siteMetadata({
      route: "/breeds/[slug]",
      locale: "en",
      params,
      title: entry.title,
      description: entry.excerpt,
    });
    expect(metadata.alternates).toEqual({
      canonical: `${origin}/en/dog-breeds/german-shepherd`,
      languages: {
        pl: `${origin}/rasy-psow/owczarek-niemiecki`,
        en: `${origin}/en/dog-breeds/german-shepherd`,
        de: `${origin}/de/hunderassen/deutscher-schaeferhund`,
        "x-default": `${origin}/rasy-psow/owczarek-niemiecki`,
      },
    });
    // A page whose parameter has another name says which.
    expect(
      content.contentVersions(entry.versions.slice(0, 1), "chapter"),
    ).toEqual({ pl: { chapter: "owczarek-niemiecki" } });
  });

  it("gets today's address parts for an entry that moved, and writes one address of them", async () => {
    const { content, site } = await load();
    const to = { type: "breeds", locale: "pl", slug: "owczarek-niemiecki" };
    fetched.mockResolvedValue(json({ entry: null, moved: to }));

    const result = await content.contentEntry({
      type: "breeds",
      locale: "en",
      slug: "german-shepherd",
    });

    expect(result).toEqual({ kind: "moved", to });
    // What the page then answers one 308 to (`permanentRedirect`).
    expect(
      result.kind === "moved" &&
        site.siteHref("/breeds/[slug]", result.to.locale, {
          slug: result.to.slug,
        }),
    ).toBe("/rasy-psow/owczarek-niemiecki");
  });

  it("says not-found for what is not published, and fails loudly when the backend does", async () => {
    const { content } = await load();
    fetched.mockResolvedValueOnce(json({ code: "content_not_found" }, 404));
    fetched.mockResolvedValueOnce(json({}, 500));
    const ask = () =>
      content.contentEntry({ type: "breeds", locale: "pl", slug: "szkic" });

    expect(await ask()).toEqual({ kind: "not-found" });
    await expect(ask()).rejects.toThrow("500");
  });

  it("keeps a slug that is no slug inside its own path segment", async () => {
    const { content } = await load();
    fetched.mockResolvedValue(json({}, 404));

    await content.contentEntry({
      type: "breeds",
      locale: "pl",
      slug: "../../sites/?x=1",
    });

    expect(new URL(asked()).pathname).toBe(
      "/api/v1/public/content/types/breeds/entries/pl/..%2F..%2Fsites%2F%3Fx%3D1/",
    );
    expect(new URL(asked()).search).toBe("");
  });
});

describe("a product's page reads a list (ADR-079)", () => {
  it("asks for a page of a type, or of one term of it", async () => {
    const { content } = await load();
    const list = { type: "breeds", locale: "pl", items: [], indexable: false };
    fetched.mockImplementation(async () => json({ list, moved: null }));

    const all = await content.contentEntries({ type: "breeds", locale: "pl" });
    await content.contentEntries({
      type: "breeds",
      locale: "pl",
      page: 2,
      pageSize: 12,
      taxonomy: "tag",
      term: "porady",
    });

    expect(all).toEqual({ kind: "list", list });
    expect(asked(0)).toBe(
      "http://127.0.0.1:8000/api/v1/public/content/types/breeds/entries/?locale=pl",
    );
    expect(Object.fromEntries(new URL(asked(1)).searchParams)).toEqual({
      locale: "pl",
      page: "2",
      page_size: "12",
      taxonomy: "tag",
      term: "porady",
    });
  });

  it("says not-found for a list nothing is on, and moved when a term changed address", async () => {
    const { content } = await load();
    const to = { type: "breeds", locale: "pl", taxonomy: "tag", term: "rady" };
    fetched.mockResolvedValueOnce(json({}, 404));
    fetched.mockResolvedValueOnce(json({ list: null, moved: to }));
    const ask = () =>
      content.contentEntries({
        type: "breeds",
        locale: "pl",
        taxonomy: "tag",
        term: "porady",
      });

    expect(await ask()).toEqual({ kind: "not-found" });
    expect(await ask()).toEqual({ kind: "moved", to });
  });

  it("reads types and terms, and nothing where the deployment has no publisher", async () => {
    const { content } = await load();
    fetched.mockResolvedValueOnce(json([{ key: "breeds" }]));
    fetched.mockResolvedValueOnce(json({}, 404));
    fetched.mockResolvedValueOnce(json({}, 404));

    expect(await content.contentTypes()).toEqual([{ key: "breeds" }]);
    expect(
      await content.contentTerms({ type: "breeds", locale: "de" }),
    ).toBeNull();
    expect(await content.contentSitemap()).toEqual({
      entries: [],
      lists: [],
      terms: [],
    });
    expect(asked(1)).toBe(
      "http://127.0.0.1:8000/api/v1/public/content/types/breeds/terms/?locale=de",
    );
  });
});

describe("the platform's content in the product's sitemap (ADR-079, ADR-080)", () => {
  const listing = {
    entries: [
      {
        type: "breeds",
        versions: [
          {
            locale: "pl",
            slug: "labrador",
            updated_at: "2026-10-01T08:00:00Z",
          },
          {
            locale: "en",
            slug: "labrador",
            updated_at: "2026-10-03T08:00:00Z",
          },
        ],
      },
      // Redirected by the product since: the core leaves the line out.
      {
        type: "breeds",
        versions: [
          {
            locale: "pl",
            slug: "owczarek",
            updated_at: "2026-10-02T08:00:00Z",
          },
        ],
      },
      // A type the product shows nowhere.
      {
        type: "news",
        versions: [
          { locale: "pl", slug: "nowina", updated_at: "2026-10-02T08:00:00Z" },
        ],
      },
    ],
    lists: [
      {
        type: "breeds",
        versions: [
          { locale: "pl", updated_at: "2026-10-02T08:00:00Z" },
          { locale: "en", updated_at: "2026-10-03T08:00:00Z" },
        ],
      },
    ],
    terms: [
      {
        type: "breeds",
        taxonomy: "tag",
        versions: [
          { locale: "pl", slug: "porady", updated_at: "2026-10-02T08:00:00Z" },
        ],
      },
    ],
  };

  it("names pages of the table with parameters per language; the core writes the addresses", async () => {
    const { content, seo, site, rules } = await load();
    fetched.mockResolvedValue(json(listing));

    const lines = await content.contentSitemapEntries({
      // No page for a tag's list in this product: those lines are left out.
      breeds: { entry: "/breeds/[slug]", list: "/breeds" },
    });

    expect(lines).toEqual([
      {
        route: "/breeds",
        params: { pl: {}, en: {} },
        lastModified: "2026-10-03T08:00:00Z",
      },
      {
        route: "/breeds/[slug]",
        params: { pl: { slug: "labrador" }, en: { slug: "labrador" } },
        lastModified: "2026-10-03T08:00:00Z",
      },
      {
        route: "/breeds/[slug]",
        params: { pl: { slug: "owczarek" } },
        lastModified: "2026-10-02T08:00:00Z",
      },
    ]);
    expect(
      seo
        .siteSitemapLines(site.productSite!, rules, lines)
        .map((line) => line.url),
    ).toEqual([
      // The list in the two languages it has entries in — not in German,
      // although the table has the page there.
      `${origin}/rasy-psow`,
      `${origin}/en/dog-breeds`,
      `${origin}/rasy-psow/labrador`,
      `${origin}/en/dog-breeds/labrador`,
    ]);
  });

  it("writes no line for an item that names no language", async () => {
    const { content } = await load();
    fetched.mockResolvedValue(
      json({
        entries: [{ type: "breeds", versions: [] }],
        lists: [{ type: "breeds", versions: [] }],
        terms: [],
      }),
    );

    // `{}` as parameters would mean "every language of the table".
    expect(
      await content.contentSitemapEntries({
        breeds: { entry: "/breeds/[slug]", list: "/breeds" },
      }),
    ).toEqual([]);
  });

  it("gives a term's list its page where the product has one", async () => {
    const { content } = await load();
    fetched.mockResolvedValue(json(listing));

    const lines = await content.contentSitemapEntries({
      breeds: { terms: { tag: "/breeds/tag/[term]" } },
    });

    expect(lines).toEqual([
      {
        route: "/breeds/tag/[term]",
        params: { pl: { term: "porady" } },
        lastModified: "2026-10-02T08:00:00Z",
      },
    ]);
  });
});
