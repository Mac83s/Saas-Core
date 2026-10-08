import { readFileSync } from "node:fs";
import path from "node:path";

import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";

import {
  compileOldAddresses,
  compileProductSite,
  type ProductOldAddresses,
  type ProductPublicSite,
} from "#lib/product-site/table";
import { deployment as rendered } from "../../generated/deployment";
import { RESERVED_SEGMENTS } from "../../proxy-segments";
import { GONE_WORDS } from "./gone-page";

/**
 * The table a product declares, held to the contract (ADR-080) — this
 * repository's own slot, whatever it says, so the test runs in every
 * product's gate and a table that cannot be served stops there, before a
 * visitor meets it. The same checks run on the test-only table, so they are
 * not empty where the slot is.
 *
 * The profile is the repository's own with the core's marketing switched
 * off: a product's pages answer only there, and the table must be right
 * whichever of its profiles is rendered.
 */
vi.mock("../../generated/deployment", async (original) => {
  const { deployment } =
    await original<typeof import("../../generated/deployment")>();
  return {
    deployment: {
      ...deployment,
      features: { ...deployment.features, marketingSite: false },
    },
  };
});

const registry: { locales: { code: string }[] } = JSON.parse(
  readFileSync(
    path.resolve(
      __dirname,
      "../../../../../packages/contracts/locales/registry.json",
    ),
    "utf8",
  ),
);
const registered = registry.locales.map((locale) => locale.code);
const profileLocales: readonly string[] = rendered.product.supportedLocales;

/** A parameter value that is certainly an address: the checks need one. */
const sampleParams = (route: string) =>
  Object.fromEntries(
    [...route.matchAll(/\[([A-Za-z0-9]+)\]/g)].map(([, name]) => [
      name,
      "sample-1",
    ]),
  );

function hold(
  name: string,
  declared: ProductPublicSite | null,
  rules: ProductOldAddresses,
  locales: readonly string[],
) {
  describe(name, () => {
    const options = {
      locales,
      defaultLocale: "pl",
      reserved: RESERVED_SEGMENTS,
    };

    it("names only languages of the registry", () => {
      const named = Object.values(declared?.routes ?? {}).flatMap(
        (addresses) =>
          typeof addresses === "string" ? [] : Object.keys(addresses),
      );
      expect(
        [...new Set(named)].filter((code) => !registered.includes(code)),
      ).toEqual([]);
    });

    it("compiles, and routes every address it writes", () => {
      if (!declared) return;
      const site = compileProductSite(declared, options);
      for (const route of site.routes) {
        const params = sampleParams(route);
        for (const { locale, path: address } of site.versions(route, params)) {
          expect(site.match(address), address).toMatchObject({
            kind: "page",
            route,
            locale,
          });
        }
      }
    });

    it("leads every old address to a page of the table, in one step", () => {
      if (!declared) {
        // Rules need a table to lead into.
        expect(rules.moved ?? {}).toEqual({});
        expect(rules.gone ?? []).toEqual([]);
        return;
      }
      const site = compileProductSite(declared, options);
      const compiled = compileOldAddresses(rules, site, RESERVED_SEGMENTS);
      for (const source of compiled.sources()) {
        const rule = compiled.lookup(source);
        if (rule?.kind !== "moved") continue;
        expect(site.match(rule.to)?.kind, `${source} → ${rule.to}`).toBe(
          "page",
        );
        expect(compiled.lookup(rule.to), `${source} → ${rule.to}`).toBeNull();
      }
    });
  });
}

const { publicSite } = await vi.importActual<
  typeof import("../../product/public-site")
>("../../product/public-site");
const { oldAddresses } = await vi.importActual<
  typeof import("../../product/old-addresses")
>("../../product/old-addresses");
const { fixtureDeployment, fixtureOldAddresses, fixtureSite } =
  await import("./fixture");

hold("the product's own table", publicSite, oldAddresses, profileLocales);
hold("the test-only table", fixtureSite, fixtureOldAddresses, [
  "pl",
  "en",
  "de",
  "es",
  "ru",
]);

/** A compared source, written the way a browser sends it. */
const asVisited = (source: string) =>
  `/${source.slice(1).split("/").map(encodeURIComponent).join("/")}`;

function walkThroughTheProxy(
  name: string,
  prepare: () => void,
  rulesAtLeast: number,
) {
  describe(`${name}, through the proxy`, () => {
    async function load() {
      vi.resetModules();
      prepare();
      const { default: proxy } = await import("../../proxy");
      const visit = (address: string) =>
        proxy(
          new NextRequest(`http://localhost${address}`, {
            headers: { host: "localhost" },
          }),
        );
      return {
        visit,
        site: await import("./site"),
        old: await import("./old-addresses"),
      };
    }

    it("is served as declared: nothing switched the pages or the rules off", async () => {
      const { site, old } = await load();

      expect(site.productSiteProblem).toBeNull();
      expect(old.productOldAddressesProblem).toBeNull();
      expect(Boolean(site.productSite)).toBe(site.productSiteDeclared);
    });

    it("answers every old address with one redirect, and its target with a page", async () => {
      const { visit, old } = await load();
      const rules = old.productOldAddresses;
      expect(rules?.size ?? 0).toBeGreaterThanOrEqual(rulesAtLeast);

      // Each source as it is compared, sent as a browser would send it —
      // however the product wrote it down.
      for (const source of rules?.sources() ?? []) {
        const rule = rules?.lookup(source);
        const answered = await visit(asVisited(source));
        if (rule?.kind !== "moved") {
          expect(answered.status, source).toBe(410);
          continue;
        }
        expect(answered.status, source).toBe(308);
        const location = new URL(answered.headers.get("location") ?? "");
        expect(location.pathname, source).toBe(rule.to);
        // The proxy's own corrections — a trailing slash, the default
        // language's prefix, a disabled feature — must not stand in the way.
        const arrived = await visit(location.pathname);
        expect(arrived.status, rule.to).toBe(200);
        expect(arrived.headers.get("x-middleware-rewrite"), rule.to).toMatch(
          /\/product-site\/[a-z]{2}(\/(?!_unclaimed)|$)/,
        );
      }
    });

    it("answers every address of the table with its page", async () => {
      const { visit, site } = await load();
      const { productSite } = site;
      if (!productSite) return;

      for (const route of productSite.routes) {
        const versions = productSite.versions(route, sampleParams(route));
        for (const { locale, path: address } of versions) {
          const response = await visit(address);
          // A page of the table must not look like something the proxy
          // refuses first (a disabled feature's address, an old address).
          expect(response.status, address).toBe(200);
          expect(response.headers.get("x-middleware-rewrite"), address).toMatch(
            new RegExp(`/product-site/${locale}(/(?!_unclaimed)|$)`),
          );
        }
      }
    });
  });
}

// The repository's own slot, in its own profile (marketing off, above).
walkThroughTheProxy(
  "the product's own table",
  () => {
    vi.doUnmock("../../product/public-site");
    vi.doUnmock("../../product/old-addresses");
  },
  0,
);
// The same walk over the test-only table, so it is not empty where the slot is.
walkThroughTheProxy(
  "the test-only table",
  () => {
    vi.doMock("../../generated/deployment", () => ({
      deployment: fixtureDeployment(),
    }));
    vi.doMock("../../product/public-site", () => ({ publicSite: fixtureSite }));
    vi.doMock("../../product/old-addresses", () => ({
      oldAddresses: fixtureOldAddresses,
    }));
  },
  8,
);

describe("the page of a gone address", () => {
  it("has its words in every language of the registry", () => {
    expect(registered.filter((code) => !GONE_WORDS[code])).toEqual([]);
  });
});
