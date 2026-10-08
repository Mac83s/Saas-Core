import { describe, expect, it } from "vitest";

import {
  compileOldAddresses,
  compileProductSite,
  normalizeOldAddress,
  ProductSiteError,
  type ProductOldAddresses,
  type ProductPublicSite,
  type SiteOptions,
} from "./table";
import { fixtureOldAddresses, fixtureSite } from "./fixture";
import { RESERVED_SEGMENTS } from "../../proxy-segments";

const options: SiteOptions = {
  locales: ["pl", "en", "de", "es", "ru"],
  defaultLocale: "pl",
  reserved: RESERVED_SEGMENTS,
};
const site = compileProductSite(fixtureSite, options);

const table = (routes: ProductPublicSite["routes"]) => () =>
  compileProductSite({ routes }, options);
const rules = (declared: ProductOldAddresses) => () =>
  compileOldAddresses(declared, site, RESERVED_SEGMENTS);

describe("a product's table of public addresses (ADR-080)", () => {
  it("answers the home page at / and under each language", () => {
    expect(site.match("/")).toMatchObject({
      route: "/",
      locale: "pl",
      page: "/",
    });
    expect(site.match("/ru")).toMatchObject({
      route: "/",
      locale: "ru",
      page: "/",
    });
    expect(site.href("/", "pl")).toBe("/");
    expect(site.href("/", "de")).toBe("/de");
  });

  it("names a section per language and answers it with one page file", () => {
    for (const [address, locale] of [
      ["/rasy-psow/labrador", "pl"],
      ["/en/dog-breeds/labrador", "en"],
      ["/de/hunderassen/labrador", "de"],
    ]) {
      expect(site.match(address!)).toEqual({
        kind: "page",
        route: "/breeds/[slug]",
        locale,
        params: { slug: "labrador" },
        page: "/breeds/labrador",
      });
    }
  });

  it("answers a section's name only in its own language", () => {
    expect(site.match("/en/rasy-psow/labrador")).toBeNull();
    expect(site.match("/dog-breeds/labrador")).toBeNull();
    // Spanish has no such section at all.
    expect(site.match("/es/dog-breeds/labrador")).toBeNull();
    expect(site.languages("/breeds/[slug]")).toEqual(["pl", "en", "de"]);
    // The page file's own path is not an address.
    expect(site.match("/breeds/labrador")).toBeNull();
  });

  it("gives one string to every content language of the profile", () => {
    expect(site.languages("/quiz")).toEqual(["pl", "en", "de", "es", "ru"]);
    expect(site.href("/quiz", "es")).toBe("/es/quiz");
  });

  it("prefers a name over a parameter in the same place", () => {
    expect(site.match("/rasy-psow/porownaj")).toMatchObject({
      route: "/breeds/compare",
    });
    expect(site.match("/de/hunderassen/compare")).toMatchObject({
      route: "/breeds/[slug]",
      params: { slug: "compare" },
    });
  });

  it("prefers a name wherever it stands, whatever order the table is written in", () => {
    const routes = {
      "/s/[x]/[y]": { pl: "/s/[x]/[y]" },
      "/s/[x]/end": { pl: "/s/[x]/koniec" },
      "/s/first/[y]": { pl: "/s/pierwszy/[y]" },
      "/s": { pl: "/s" },
      "/s/first/end": { pl: "/s/pierwszy/koniec" },
    };
    for (const order of [
      Object.entries(routes),
      Object.entries(routes).reverse(),
    ]) {
      const mixed = compileProductSite(
        { routes: Object.fromEntries(order) },
        options,
      );
      expect(mixed.match("/s/pierwszy/koniec")).toMatchObject({
        route: "/s/first/end",
      });
      expect(mixed.match("/s/pierwszy/inny")).toMatchObject({
        route: "/s/first/[y]",
      });
      expect(mixed.match("/s/inny/koniec")).toMatchObject({
        route: "/s/[x]/end",
      });
      expect(mixed.match("/s/inny/jeszcze")).toMatchObject({
        route: "/s/[x]/[y]",
        params: { x: "inny", y: "jeszcze" },
      });
    }
  });

  it("takes an address in one spelling only", () => {
    for (const address of [
      "/Rasy-Psow/labrador",
      "/rasy-psow/Labrador",
      "/rasy-psow/labrador/",
      "//rasy-psow/labrador",
      "/rasy-psow/%6Cabrador",
      "/rasy-psow/żółw",
      "/rasy-psow/a_b",
      "/EN/dog-breeds/labrador",
    ]) {
      expect(site.match(address), address).toBeNull();
    }
  });

  it("calls the default language under its own prefix a spelling to correct", () => {
    expect(site.match("/pl/rasy-psow/labrador")).toEqual({
      kind: "canonical",
      path: "/rasy-psow/labrador",
    });
    expect(site.match("/pl")).toEqual({ kind: "canonical", path: "/" });
    expect(site.match("/pl/nie-ma")).toBeNull();
  });

  it("routes every address it writes, to the page it was written for", () => {
    const samples: Record<string, Record<string, string>> = {
      "/breeds/[slug]": { slug: "owczarek-niemiecki" },
      "/guide/[chapter]": { chapter: "rozdzial-2" },
    };
    let checked = 0;
    for (const route of site.routes) {
      for (const locale of site.languages(route)) {
        const params = samples[route] ?? {};
        const address = site.href(route, locale, params);
        expect(site.match(address), address).toMatchObject({
          kind: "page",
          route,
          locale,
          params,
        });
        checked += 1;
      }
    }
    expect(checked).toBe(5 + 3 + 3 + 2 + 5 + 1);
  });

  it("refuses to write an address it would not route", () => {
    expect(() =>
      site.href("/breeds/[slug]", "pl", { slug: "Owczarek" }),
    ).toThrow(ProductSiteError);
    expect(() => site.href("/breeds/[slug]", "pl")).toThrow(ProductSiteError);
    expect(() => site.href("/breeds/[slug]", "es", { slug: "x" })).toThrow(
      ProductSiteError,
    );
    expect(() => site.href("/nope", "pl")).toThrow(ProductSiteError);
  });

  it("lists a page's versions with each language's own parameters", () => {
    expect(
      site.versions("/breeds/[slug]", {
        pl: { slug: "owczarek-niemiecki" },
        en: { slug: "german-shepherd" },
      }),
    ).toEqual([
      { locale: "pl", path: "/rasy-psow/owczarek-niemiecki" },
      { locale: "en", path: "/en/dog-breeds/german-shepherd" },
    ]);
    expect(site.versions("/breeds/[slug]", { slug: "labrador" })).toEqual([
      { locale: "pl", path: "/rasy-psow/labrador" },
      { locale: "en", path: "/en/dog-breeds/labrador" },
      { locale: "de", path: "/de/hunderassen/labrador" },
    ]);
    // A name that cannot be an address is left out, not written.
    expect(
      site.versions("/breeds/[slug]", {
        pl: { slug: "ok" },
        en: { slug: "Not OK" },
      }),
    ).toEqual([{ locale: "pl", path: "/rasy-psow/ok" }]);
    expect(site.versions("/breeds").map((version) => version.locale)).toEqual([
      "pl",
      "en",
      "de",
    ]);
  });

  it("leaves out a language the profile does not offer, but still checks it", () => {
    const narrow = compileProductSite(fixtureSite, {
      ...options,
      locales: ["pl", "en"],
    });
    expect(narrow.languages("/breeds")).toEqual(["pl", "en"]);
    expect(narrow.match("/de/hunderassen/labrador")).toBeNull();
    expect(() =>
      compileProductSite(
        { routes: { "/a": { pl: "/a", de: "/panel" } } },
        { ...options, locales: ["pl", "en"] },
      ),
    ).toThrow(/platform's own/);
  });

  it.each([
    ["two pages at one address", { "/a": { pl: "/x" }, "/b": { pl: "/x" } }],
    [
      "two patterns that are one",
      { "/a/[x]": { pl: "/s/[x]" }, "/b/[y]": { pl: "/s/[y]" } },
    ],
    ["letters beyond a–z", { "/a": { pl: "/żółw" } }],
    ["upper case", { "/a": { pl: "/Rasy" } }],
    ["a trailing slash", { "/a": { pl: "/rasy/" } }],
    ["the panel's address", { "/a": { pl: "/panel" } }],
    ["a guest's address", { "/a": { en: "/book" } }],
    ["the platform's media", { "/a": { pl: "/media" } }],
    ["what the proxy never sees", { "/a": { pl: "/apiary" } }],
    ["a language in front", { "/a": { pl: "/de" } }],
    ["a parameter in front", { "/[x]": { pl: "/[x]" } }],
    ["other parameters than the page's", { "/a/[x]": { pl: "/a/[y]" } }],
    ["a parameter missing", { "/a/[x]": { pl: "/a" } }],
    ["the home address for another page", { "/a": { pl: "/" } }],
    ["another address for the home page", { "/": { pl: "/start" } }],
    ["a language that is none", { "/a": { polish: "/a" } }],
  ])("refuses %s", (_name, routes) => {
    expect(table(routes)).toThrow(ProductSiteError);
  });
});

describe("how an old address is compared (ADR-080)", () => {
  it.each([
    ["/Rasy/Labrador-Retriever", "/rasy/labrador-retriever"],
    ["/rasy/labrador-retriever/", "/rasy/labrador-retriever"],
    ["//rasy///labrador-retriever//", "/rasy/labrador-retriever"],
    ["/rasy/%6Cabrador-retriever", "/rasy/labrador-retriever"],
    ["/poradnik/%C5%BBywienie%20szczeniaka", "/poradnik/żywienie szczeniaka"],
    // The same letter written as one sign and as a letter with a mark.
    ["/poradnik/z\u0307ywienie", "/poradnik/\u017cywienie"],
    ["/", "/"],
  ])("%s is %s", (written, compared) => {
    expect(normalizeOldAddress(written)).toBe(compared);
  });

  it("does not compare what it cannot read", () => {
    expect(normalizeOldAddress("/rasy/%E0%A4%A")).toBeNull();
    // An encoded slash is not a path separator.
    expect(normalizeOldAddress("/rasy%2Flabrador")).toBeNull();
  });
});

describe("a product's old addresses (ADR-080)", () => {
  const compiled = compileOldAddresses(
    fixtureOldAddresses,
    site,
    RESERVED_SEGMENTS,
  );

  it("finds a rule whatever the spelling of the visit", () => {
    for (const visit of [
      "/rasy/labrador-retriever",
      "/Rasy/Labrador-Retriever/",
      "/rasy/%6Cabrador-retriever",
    ]) {
      expect(compiled.lookup(visit), visit).toEqual({
        kind: "moved",
        to: "/rasy-psow/labrador",
      });
    }
    expect(compiled.lookup("/poradnik/%C5%BBywienie%20szczeniaka")).toEqual({
      kind: "moved",
      to: "/poradnik/zywienie",
    });
    expect(compiled.lookup("/rasy/labrador")).toBeNull();
    expect(compiled.lookup("/rasy/%E0%A4%A")).toBeNull();
  });

  it("says gone in the language the address was asked in", () => {
    expect(compiled.lookup("/sklep")).toEqual({ kind: "gone", locale: "pl" });
    expect(compiled.lookup("/EN/Shop/old-offer/")).toEqual({
      kind: "gone",
      locale: "en",
    });
    expect(compiled.lookup("/de/laden")).toEqual({
      kind: "gone",
      locale: "de",
    });
  });

  it("leads every moved address to a page, in one step", () => {
    for (const source of compiled.sources()) {
      const rule = compiled.lookup(source);
      if (rule?.kind !== "moved") continue;
      expect(site.match(rule.to)?.kind, rule.to).toBe("page");
      expect(compiled.lookup(rule.to), rule.to).toBeNull();
    }
    expect(compiled.size).toBe(7);
  });

  it.each([
    ["a chain", { moved: { "/a": "/rasy-psow/b", "/rasy-psow/b": "/quiz" } }],
    [
      "a loop of two",
      {
        moved: {
          "/rasy-psow/a": "/rasy-psow/b",
          "/rasy-psow/b": "/rasy-psow/a",
        },
      },
    ],
    ["a loop of one", { moved: { "/rasy-psow/a": "/rasy-psow/a" } }],
    [
      "a target that is gone",
      { moved: { "/a": "/rasy-psow/b" }, gone: ["/rasy-psow/b"] },
    ],
    ["a target outside the table", { moved: { "/a": "/nowa" } }],
    [
      "a target on another host",
      { moved: { "/a": "https://example.test/quiz" } },
    ],
    ["a target with a trailing slash", { moved: { "/a": "/quiz/" } }],
    [
      "a target under the default language's prefix",
      { moved: { "/a": "/pl/quiz" } },
    ],
    ["a target in another spelling", { moved: { "/a": "/Quiz" } }],
    ["a target in the panel", { moved: { "/a": "/login" } }],
    ["the same address twice", { moved: { "/a": "/quiz" }, gone: ["/A/"] }],
    ["a page of the table", { gone: ["/quiz"] }],
    [
      "a page of the table in another language",
      { moved: { "/en/quiz": "/quiz" } },
    ],
    ["the home page", { gone: ["/"] }],
    ["a language's home page", { gone: ["/de"] }],
    ["the panel", { gone: ["/panel/old"] }],
    ["the panel under a language", { moved: { "/en/login": "/quiz" } }],
    ["a guest's page", { gone: ["/book/salon"] }],
    ["the platform's media", { gone: ["/media/old"] }],
    ["the api", { gone: ["/api/v1/old"] }],
    ["what the proxy never sees", { gone: ["/apiary"] }],
    ["an address with a dot", { gone: ["/stara-strona.html"] }],
    ["a query", { gone: ["/stara?x=1"] }],
    ["a path without its slash", { gone: ["stara"] }],
    ["what cannot be decoded", { gone: ["/stara/%E0%A4%A"] }],
  ])("refuses %s", (_name, declared) => {
    expect(rules(declared)).toThrow(ProductSiteError);
  });

  it("lets a rule lie over a section's pattern: a renamed entry", () => {
    expect(compiled.lookup("/rasy-psow/owczarek")).toEqual({
      kind: "moved",
      to: "/rasy-psow/owczarek-niemiecki",
    });
  });

  it("holds a few thousand rules", () => {
    const moved = Object.fromEntries(
      Array.from({ length: 5000 }, (_, index) => [
        `/stare/rasa-${index}`,
        `/rasy-psow/rasa-${index}`,
      ]),
    );
    const many = compileOldAddresses({ moved }, site, RESERVED_SEGMENTS);
    expect(many.size).toBe(5000);
    expect(many.lookup("/Stare/Rasa-4999/")).toEqual({
      kind: "moved",
      to: "/rasy-psow/rasa-4999",
    });
  });
});
