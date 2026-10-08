import { readFileSync } from "node:fs";
import path from "node:path";

import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { describeResponse, walk } from "../../proxy-corpus";
import { fixtureDeployment, fixtureOldAddresses, fixtureSite } from "./fixture";

/**
 * The proxy with a product that brings public pages of its own (ADR-080):
 * a test-only slot, the real proxy, next-intl's real middleware.
 */
const golden: Record<string, Record<string, string>> = JSON.parse(
  readFileSync(path.resolve(__dirname, "../../proxy.golden.json"), "utf8"),
);

type Slot = {
  deployment?: ReturnType<typeof fixtureDeployment>;
  site?: unknown;
  rules?: unknown;
};

async function load(slot: Slot = {}) {
  vi.resetModules();
  vi.doMock("../../generated/deployment", () => ({
    deployment: slot.deployment ?? fixtureDeployment(),
  }));
  vi.doMock("../../product/public-site", () => ({
    publicSite: slot.site === undefined ? fixtureSite : slot.site,
  }));
  vi.doMock("../../product/old-addresses", () => ({
    oldAddresses: slot.rules ?? fixtureOldAddresses,
  }));
  const { default: proxy } = await import("../../proxy");
  const visit = (address: string, host = "localhost:8080") =>
    proxy(
      new NextRequest(`http://${host.split(":")[0]}${address}`, {
        headers: { host },
      }),
    );
  return { proxy, visit, answers: await import("./answers") };
}

afterEach(() => {
  vi.doUnmock("../../generated/deployment");
  vi.doUnmock("../../product/public-site");
  vi.doUnmock("../../product/old-addresses");
  vi.resetModules();
  vi.restoreAllMocks();
});

const page = (locale: string, file: string) =>
  `200 rewrite=http://localhost/${locale}/product-site${file} request[x-next-intl-locale=${locale}]`;

describe("a product's public pages on its host (ADR-080)", () => {
  it("answers the home page at / and under each language", async () => {
    const { visit } = await load();

    expect(describeResponse(await visit("/"))).toBe(page("pl", ""));
    expect(describeResponse(await visit("/en"))).toBe(page("en", ""));
    expect(describeResponse(await visit("/ru"))).toBe(page("ru", ""));
  });

  it("answers a section under its name in each language, with one page file", async () => {
    const { visit } = await load();

    expect(describeResponse(await visit("/rasy-psow/labrador"))).toBe(
      page("pl", "/breeds/labrador"),
    );
    expect(describeResponse(await visit("/en/dog-breeds/labrador"))).toBe(
      page("en", "/breeds/labrador"),
    );
    expect(
      describeResponse(await visit("/de/hunderassen/labrador?tab=care")),
    ).toBe(page("de", "/breeds/labrador?tab=care"));
  });

  it("names the language itself, whatever the visitor sends", async () => {
    const { proxy } = await load();

    const response = await proxy(
      new NextRequest("http://localhost/de/hunderassen", {
        headers: {
          host: "localhost:8080",
          "x-next-intl-locale": "ru",
          "accept-language": "en",
          cookie: "NEXT_LOCALE=en",
        },
      }),
    );

    expect(describeResponse(response)).toBe(page("de", "/breeds"));
    expect(response.headers.getSetCookie()).toEqual([]);
  });

  it("uses the header name next-intl's own middleware sets", async () => {
    const { visit, answers } = await load();

    // A panel page goes through next-intl; a product page through the rewrite.
    const theirs = await visit("/en/login");
    const ours = await visit("/en/quiz");
    const name = `x-middleware-request-${answers.LOCALE_HEADER.toLowerCase()}`;

    expect(theirs.headers.get(name)).toBe("en");
    expect(ours.headers.get(name)).toBe("en");
  });

  it("drops the default language's prefix with one permanent redirect", async () => {
    const { visit } = await load();

    const response = await visit("/pl/rasy-psow/labrador?tab=care");

    expect(response.status).toBe(308);
    expect(response.headers.get("location")).toBe(
      "http://localhost:8080/rasy-psow/labrador?tab=care",
    );
    expect((await visit("/pl")).headers.get("location")).toBe(
      "http://localhost:8080/",
    );
  });

  it("corrects the prefix and a trailing slash together, in one redirect", async () => {
    const { visit } = await load();

    for (const [address, target] of [
      ["/pl/rasy-psow/labrador/?tab=care", "/rasy-psow/labrador?tab=care"],
      ["/pl/", "/"],
      ["/pl/quiz//", "/quiz"],
    ]) {
      const response = await visit(address!);
      expect(response.status, address).toBe(308);
      expect(response.headers.get("location"), address).toBe(
        `http://localhost:8080${target}`,
      );
    }
    // A slash alone stays the platform host's own rule: one step as well.
    expect(
      (await visit("/en/dog-breeds/labrador/")).headers.get("location"),
    ).toBe("http://localhost:8080/en/dog-breeds/labrador");
  });

  it.each([
    ["/en/rasy-psow/labrador", "en"],
    ["/dog-breeds/labrador", "pl"],
    ["/es/dog-breeds/labrador", "es"],
    ["/Rasy-Psow/labrador", "pl"],
    ["/rasy-psow/%6Cabrador", "pl"],
    ["/breeds/labrador", "pl"],
    ["/de/nichts", "de"],
    ["/pricing", "pl"],
    ["/en/katalog", "en"],
  ])(
    "gives %s the product's own 404, in that language",
    async (address, locale) => {
      const { visit } = await load();

      expect(describeResponse(await visit(address))).toBe(
        page(locale, "/_unclaimed"),
      );
    },
  );

  it("does not answer the folder of its page files", async () => {
    const { visit } = await load();

    for (const address of [
      "/product-site",
      "/product-site/breeds/labrador",
      "/en/product-site/breeds/labrador",
    ]) {
      const response = await visit(address);
      expect(response.status, address).toBe(404);
      expect(response.headers.get("x-middleware-rewrite"), address).toBeNull();
    }
  });

  it("does not answer that folder in any spelling the router would read, dots included", async () => {
    const { visit } = await load();

    for (const address of [
      // The matcher hands these to the proxy for this folder alone.
      "/en/product-site/breeds/a.b",
      "/product-site/quiz.html",
      "/en/%70roduct-site/quiz",
      "/en/product%2Dsite/breeds/labrador",
    ]) {
      const response = await visit(address);
      expect(response.status, address).toBe(404);
      expect(response.headers.get("x-middleware-rewrite"), address).toBeNull();
      expect(response.headers.get("x-middleware-next"), address).toBeNull();
    }
    // On a customer's host the same address is a path of that site.
    expect(
      (
        await visit("/en/product-site/breeds/a.b", "studio.example.test")
      ).headers.get("x-middleware-rewrite"),
    ).toBe(
      "http://studio.example.test/site-renderer/en/product-site/breeds/a.b",
    );
  });

  it("is handed that folder by the matcher, and lets it go untouched where no table is declared", async () => {
    const { proxy, visit } = await load({ site: null, rules: {} });
    const { config } = await import("../../proxy");

    expect(config.matcher).toContain("/product-site/:path*");
    expect(config.matcher).toContain("/:locale/product-site/:path*");
    for (const host of ["localhost:8080", "studio.example.test"]) {
      for (const address of [
        "/en/product-site/breeds/a.b",
        "/product-site/quiz.html",
      ]) {
        // Exactly what an address the matcher skips gets: nothing.
        expect(describeResponse(await visit(address, host)), address).toBe(
          "200 next",
        );
      }
    }
    // The feeds a language prefix may carry reached the proxy before, and
    // still take the path they took.
    expect(
      (await visit("/product-site/rss.xml", "studio.example.test")).headers.get(
        "x-middleware-rewrite",
      ),
    ).toBe("http://studio.example.test/site-renderer/product-site/rss.xml");
    expect(await walk(proxy)).toEqual(golden["five languages, no marketing"]);
  });

  it("leaves the platform's media and the api's neighbours alone", async () => {
    const { visit } = await load();

    // `/media` is the platform's to answer (ADR-079); until it does, 404.
    expect(describeResponse(await visit("/media/abc"))).toBe("404");
    expect(describeResponse(await visit("/en/media/abc"))).toBe("404");
  });

  it("keeps sign-in as the front door while the product has no home page", async () => {
    const { visit } = await load({
      site: { routes: { "/quiz": "/quiz" } },
      rules: {},
    });

    const root = await visit("/");

    expect(root.status).toBe(307);
    expect(root.headers.get("location")).toBe("http://localhost:8080/login");
    expect(describeResponse(await visit("/en/quiz"))).toBe(page("en", "/quiz"));
  });

  it("takes only addresses that led nowhere before", async () => {
    const { proxy } = await load();
    const before = golden["five languages, no marketing"]!;

    const now = await walk(proxy);

    const changed = Object.keys(before).filter(
      (key) => now[key] !== before[key],
    );
    // Every panel, guest, metadata and customer-site address answers as it
    // did; what changed was a 404, the way to sign-in, or a redirect that
    // now reaches a product page's address in one step instead of two.
    for (const key of changed) {
      if (before[key]!.startsWith("308 ")) {
        expect(now[key], key).toMatch(/^308 /);
        expect(key, key).toMatch(/ \/pl\/$/);
      } else {
        expect(before[key], key).toMatch(/^(404$|307 location=\S+\/login$)/);
      }
    }
    expect(changed.some((key) => key.includes("studio.example.test"))).toBe(
      false,
    );
    expect(changed.length).toBeGreaterThan(0);
  });

  it("serves nothing of its own where the profile shows the core's marketing", async () => {
    const { proxy } = await load({
      deployment: {
        ...fixtureDeployment({}, ["pl", "en", "de"]),
        id: "golden",
        product: {
          name: "Golden",
          defaultLocale: "pl",
          supportedLocales: ["pl", "en", "de"],
          platformDomain: "platform.example.test",
        },
        features: { publicBooking: true },
      } as ReturnType<typeof fixtureDeployment>,
    });

    // The table and its rules are declared, and nothing answers differently
    // — but the folder of the product's page files, which is in the build
    // all the same and must not open as an address of its own.
    const before = golden["pl-en-de"]!;
    const now = await walk(proxy);
    const folder = (key: string) =>
      / \/(?:[a-z]{2}\/)?product-site(?:\/|$)/.test(key);
    for (const key of Object.keys(before)) {
      if (folder(key) && !key.startsWith("studio.example.test")) {
        expect(now[key], key).toBe("404");
      } else {
        expect(now[key], key).toBe(before[key]);
      }
    }
    expect(Object.keys(before).filter(folder).length).toBeGreaterThan(0);
    // Dots and encoded spellings as well: a page file there would render
    // with links this profile cannot write.
    const visit = (address: string) =>
      proxy(
        new NextRequest(`http://localhost${address}`, {
          headers: { host: "localhost:8080" },
        }),
      );
    for (const address of [
      "/en/product-site/breeds/a.b",
      "/product-site/quiz.html",
      "/en/%70roduct-site/quiz",
    ]) {
      expect((await visit(address)).status, address).toBe(404);
    }
  });

  it("stays off, with the panel alive, when the table cannot be served", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { visit } = await load({
      site: { routes: { "/a": { pl: "/panel" } } },
    });

    expect((await visit("/")).headers.get("location")).toBe(
      "http://localhost:8080/login",
    );
    expect((await visit("/login")).status).toBe(200);
    expect((await visit("/rasy/labrador-retriever")).status).toBe(404);
    expect(console.error).toHaveBeenCalled();
  });
});

describe("a product's old addresses on its host (ADR-080)", () => {
  it.each([
    "/rasy/labrador-retriever",
    "/rasy/labrador-retriever/",
    "/Rasy/Labrador-Retriever",
    "/RASY/LABRADOR-RETRIEVER/",
    "/rasy/%6Cabrador-retriever",
    "//rasy//labrador-retriever",
  ])("answers %s with one 308 straight to the page", async (address) => {
    const { visit } = await load();

    const moved = await visit(`${address}?utm=x`);

    expect(moved.status).toBe(308);
    expect(moved.headers.get("location")).toBe(
      "http://localhost:8080/rasy-psow/labrador?utm=x",
    );
    expect(describeResponse(await visit("/rasy-psow/labrador?utm=x"))).toBe(
      page("pl", "/breeds/labrador?utm=x"),
    );
  });

  it("compares letters beyond a–z however they arrive", async () => {
    const { visit } = await load();

    for (const address of [
      "/poradnik/%C5%BCywienie%20szczeniaka",
      "/Poradnik/%C5%BBywienie%20szczeniaka/",
      // z + a combining dot above, as some systems send the same letter.
      "/poradnik/z%CC%87ywienie%20szczeniaka",
      // A rule written percent-encoded, visited encoded and not.
      "/blog/%C5%BBywienie-psa",
      "/blog/%C5%BCywienie-psa/",
    ]) {
      const moved = await visit(address);
      expect(moved.status, address).toBe(308);
      expect(moved.headers.get("location"), address).toBe(
        "http://localhost:8080/poradnik/zywienie",
      );
    }
  });

  it("redirects on the visitor's own host and scheme", async () => {
    const { proxy } = await load();

    const moved = await proxy(
      new NextRequest("http://internal:3000/en/breeds/labrador-retriever", {
        headers: { host: "localhost:8080", "x-forwarded-proto": "https" },
      }),
    );

    expect(moved.headers.get("location")).toBe(
      "https://localhost:8080/en/dog-breeds/labrador",
    );
  });

  it("answers a gone address with 410 and a small page in its language", async () => {
    const { visit } = await load();

    const polish = await visit("/sklep/");
    const english = await visit("/en/shop/old-offer");
    const german = await visit("/DE/Laden");

    for (const response of [polish, english, german]) {
      expect(response.status).toBe(410);
      expect(response.headers.get("content-type")).toBe(
        "text/html; charset=utf-8",
      );
      expect(response.headers.get("x-robots-tag")).toBe("noindex");
    }
    expect(await polish.text()).toContain('<html lang="pl">');
    const body = await english.text();
    expect(body).toContain('<html lang="en">');
    expect(body).toContain("This page is gone");
    expect(body).toContain('<a href="/en">Home page</a>');
    expect(await german.text()).toContain('<a href="/de">Startseite</a>');
  });

  it("never answers on a customer's site", async () => {
    const { proxy, visit } = await load();
    const before = golden["five languages, no marketing"]!;

    // A customer's site may have these very addresses of its own.
    for (const address of [
      "/",
      "/sklep",
      "/rasy/labrador-retriever",
      "/rasy-psow/labrador",
      "/en/dog-breeds/labrador",
      "/pl/rasy-psow/labrador",
    ]) {
      expect(
        describeResponse(await visit(address, "studio.example.test")),
        address,
      ).toBe(
        `200 rewrite=http://studio.example.test/site-renderer${address === "/" ? "" : address} request[x-saas-core-site-method=GET, x-saas-core-site-path=${address}, x-saas-core-site-trailing-slash=0]`,
      );
    }
    // And the recorded addresses of a customer's site, one by one.
    const now = await walk(proxy);
    const customer = Object.keys(before).filter((key) =>
      key.startsWith("studio.example.test"),
    );
    expect(customer.length).toBe(51);
    for (const key of customer) expect(now[key], key).toBe(before[key]);
  });

  it("holds every rule to one step, through the proxy's own corrections", async () => {
    const { visit } = await load({
      // Booking off: the proxy refuses addresses that look like booking's.
      deployment: fixtureDeployment({ publicBooking: false }),
    });

    for (const [source, target] of Object.entries(fixtureOldAddresses.moved!)) {
      const moved = await visit(source);
      expect(moved.status, source).toBe(308);
      expect(new URL(moved.headers.get("location")!).pathname).toBe(target);
      const arrived = await visit(target);
      expect(arrived.status, target).toBe(200);
      expect(arrived.headers.get("x-middleware-rewrite"), target).toContain(
        "/product-site/",
      );
      expect(arrived.headers.get("x-middleware-rewrite"), target).not.toContain(
        "_unclaimed",
      );
    }
  });
});
