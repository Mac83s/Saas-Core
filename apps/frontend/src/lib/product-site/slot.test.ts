import { existsSync, readFileSync, readdirSync } from "node:fs";
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

describe("the product's own page files", () => {
  // The proxy hands a visit to these; a table without them answers nothing
  // a visitor could read. The core has no table and ships none of them.
  it.each(["layout.tsx", "not-found.tsx", "[...rest]/page.tsx"])(
    "has %s under app/product-site/[locale] when a table is declared",
    (file) => {
      if (!publicSite) return;
      const folder = path.resolve(__dirname, "../../app/product-site/[locale]");

      expect(existsSync(path.join(folder, file)), file).toBe(true);
    },
  );
});

/**
 * A page that keeps what it rendered (`export const revalidate`) while it
 * reads the core's content client answers 500 at its first visit on a built
 * application: the read is `no-store` unless told otherwise, and a kept page
 * must not meet one. `export const dynamic = "force-static"` in the page file
 * is what lets it be kept; typecheck, the other tests and the build say
 * nothing (contract §4, ADR-080 PR1d).
 *
 * The rule reads sources, it renders nothing:
 *
 * - "reads the content client" means the page file reaches
 *   `#lib/product-site/content` through value imports — relative ones and the
 *   package's `#…` names, through the product's own modules, however deep.
 *   An import is not a call: a kept page that imports a module only for
 *   something else in it, or passes `revalidate` to every read, is asked for
 *   the line all the same (it costs such a page nothing).
 * - Not seen: `import()`, a read written without the client (the page's own
 *   `fetch`), and `revalidate` or `dynamic` said by a layout instead of the
 *   page file. Where `generateStaticParams` stands is not looked at — a page
 *   without parameters gets its languages from the layout's.
 * - `revalidate = 0` keeps nothing; `false` keeps for good and counts.
 *   A page that says `force-dynamic` is rendered at every visit and is fine.
 */
const CONTENT_CLIENT = "lib/product-site/content.ts";
const IMPORTED =
  /(?:^|\n)\s*(?:import|export)\s+(?!type\b)(?:[^'";]*?\sfrom\s*)?["']([^"']+)["']/g;

/** A source by its path under `src`, or null where there is no such file. */
type ReadSource = (file: string) => string | null;

function reachesContentClient(
  file: string,
  read: ReadSource,
  seen = new Set<string>(),
): boolean {
  if (file === CONTENT_CLIENT) return true;
  if (seen.has(file)) return false;
  seen.add(file);
  return [...(read(file) ?? "").matchAll(IMPORTED)].some(([, name = ""]) => {
    const base = name.startsWith("#")
      ? name.slice(1)
      : name.startsWith(".")
        ? path.posix.join(path.posix.dirname(file), name)
        : null;
    if (base === null) return false;
    const imported = [
      base,
      `${base}.ts`,
      `${base}.tsx`,
      `${base}/index.ts`,
      `${base}/index.tsx`,
    ].find(
      (candidate) =>
        /\.tsx?$/.test(candidate) &&
        (candidate === CONTENT_CLIENT || read(candidate) !== null),
    );
    return Boolean(imported) && reachesContentClient(imported!, read, seen);
  });
}

function keptOverContentRead(page: string, read: ReadSource): boolean {
  const source = read(page) ?? "";
  const keeps = /^export const revalidate\s*=\s*([^;\n]+)/m.exec(source);
  return (
    Boolean(keeps) &&
    keeps?.[1]?.trim() !== "0" &&
    !/^export const dynamic\s*=\s*["']force-(?:static|dynamic)["']/m.test(
      source,
    ) &&
    reachesContentClient(page, read)
  );
}

describe("a page kept over the content read", () => {
  const src = path.resolve(__dirname, "../..");
  const fromDisk: ReadSource = (file) => {
    try {
      return readFileSync(path.join(src, file), "utf8");
    } catch {
      return null;
    }
  };
  const folder = "app/product-site/[locale]";

  // The core ships no page files; in a product these are its own.
  it('has `dynamic = "force-static"` in every page file kept over the content read', () => {
    const pages = existsSync(path.join(src, folder))
      ? readdirSync(path.join(src, folder), { recursive: true })
          .map((file) => String(file).split(path.sep).join("/"))
          .filter((file) => /(^|\/)page\.tsx$/.test(file))
          .map((file) => `${folder}/${file}`)
      : [];

    expect(pages.filter((page) => keptOverContentRead(page, fromDisk))).toEqual(
      [],
    );
  });

  // The same rule on sample sources, so it is not empty where the folder is.
  const direct = `import { contentEntry } from "#lib/product-site/content";\n`;
  const throughModules = `import { ListRoute } from "../../../../../product/site/blog/list-route";\n`;
  const kept = `export const revalidate = 300;\nexport function generateStaticParams() {\n  return [];\n}\n`;
  const page = `${folder}/blog/[slug]/page.tsx`;
  const modules = {
    "product/site/blog/list-route.tsx": `import { readList } from "./data";\n`,
    "product/site/blog/data.ts": `import "server-only";\nimport {\n  contentEntries,\n  contentTerms,\n} from "#lib/product-site/content";\n`,
    "product/site/breeds/data.ts": `import type { ContentListResult } from "#lib/product-site/content";\nimport { siteHas } from "#lib/product-site/site";\n`,
    "lib/product-site/site.ts": `export { productSite } from "./table";\n`,
  };
  it.each([
    ["a kept page that reads the client", `${direct}${kept}`, true],
    [
      "a kept page that reads it through the product's modules",
      `${throughModules}${kept}`,
      true,
    ],
    [
      "a page kept for good",
      `${direct}export const revalidate = false;\n`,
      true,
    ],
    [
      "the same page with force-static",
      `${direct}export const dynamic = "force-static";\n${kept}`,
      false,
    ],
    [
      "a page rendered at every visit",
      `${direct}export const dynamic = "force-dynamic";\n${kept}`,
      false,
    ],
    ["a page that keeps nothing", direct, false],
    [
      "a page that says revalidate = 0",
      `${direct}export const revalidate = 0;\n`,
      false,
    ],
    [
      "a kept page over a module that takes only a type from the client",
      `import { readBreed } from "../../../../../product/site/breeds/data";\n${kept}`,
      false,
    ],
  ])("%s — a finding: $2", (_name, source, finding) => {
    const sources: Record<string, string> = { ...modules, [page]: source };

    expect(keptOverContentRead(page, (file) => sources[file] ?? null)).toBe(
      finding,
    );
  });
});

describe("the page of a gone address", () => {
  it("has its words in every language of the registry", () => {
    expect(registered.filter((code) => !GONE_WORDS[code])).toEqual([]);
  });
});
