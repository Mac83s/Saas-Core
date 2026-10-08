// @vitest-environment node
import http from "node:http";
import https from "node:https";

import { describe, expect, it } from "vitest";

import { deployment } from "../../generated/deployment";
import { oldAddresses } from "../../product/old-addresses";
import { publicSite } from "../../product/public-site";
import { RESERVED_SEGMENTS } from "../../proxy-segments";
import { compileOldAddresses, compileProductSite } from "./table";

/**
 * This repository's public pages, asked of a running stack (ADR-080) — the
 * half no test of the table can see. The table knows an address's shape; only
 * the built pages know whether `/rasy-psow/labrador` is a breed. A moved rule
 * with a mistyped target passes every other check, answers 308, lands on the
 * page's own 404, and browsers remember the 308.
 *
 * Skipped unless told where the stack is; part of a product's acceptance
 * after every rebuild that changed its table, its rules or its pages:
 *
 *   PRODUCT_SITE_URL=http://127.0.0.1:8083 PRODUCT_SITE_HOST=product.localhost \
 *     pnpm --filter @saas-core/frontend product-site:check
 *
 * `PRODUCT_SITE_HOST` is the platform host the stack answers to (the `Host`
 * header); `PRODUCT_SITE_LOCALES` (`pl,en,de`) the languages of the profile
 * the stack runs, when it is not the rendered one.
 */
const base = process.env.PRODUCT_SITE_URL;
const host = process.env.PRODUCT_SITE_HOST;
const locales =
  process.env.PRODUCT_SITE_LOCALES?.split(",").map((code) => code.trim()) ??
  deployment.product.supportedLocales;

type Answer = { status: number; location: string | null; body: string };

function ask(address: string): Promise<Answer> {
  const url = new URL(address, base);
  const client = url.protocol === "https:" ? https : http;
  return new Promise((resolve, reject) => {
    const request = client.request(
      url,
      { method: "GET", headers: host ? { host } : {} },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (chunk: Buffer) => chunks.push(chunk));
        response.on("end", () =>
          resolve({
            status: response.statusCode ?? 0,
            location: response.headers.location ?? null,
            body: Buffer.concat(chunks).toString("utf8"),
          }),
        );
      },
    );
    request.on("error", reject);
    request.end();
  });
}

/** Runs `work` over `items`, a few at a time: a stack is not a benchmark. */
async function each<T>(items: readonly T[], work: (item: T) => Promise<void>) {
  const queue = [...items];
  await Promise.all(
    Array.from({ length: 8 }, async () => {
      for (let item = queue.shift(); item !== undefined; item = queue.shift()) {
        await work(item);
      }
    }),
  );
}

/** A compared source, written the way a browser sends it. */
const asVisited = (source: string) =>
  `/${source.slice(1).split("/").map(encodeURIComponent).join("/")}`;

/** The path and query of a Location, wherever it points. */
const pathOf = (location: string | null) => {
  if (location === null) return null;
  const url = new URL(location, "http://stack.invalid");
  return `${url.pathname}${url.search}`;
};

describe.skipIf(!base)("the product's public pages on the built stack", () => {
  const site = publicSite
    ? compileProductSite(publicSite, {
        locales,
        defaultLocale: "pl",
        reserved: RESERVED_SEGMENTS,
      })
    : null;
  const rules = site
    ? compileOldAddresses(oldAddresses, site, RESERVED_SEGMENTS)
    : null;

  it("says it serves them: /healthz is ok", async () => {
    const health = await ask("/healthz");

    expect(health.status, health.body).toBe(200);
  });

  it("answers every old address with one redirect that ends on a page, or with 410", async () => {
    const wrong: string[] = [];
    await each(rules?.sources() ?? [], async (source) => {
      const rule = rules?.lookup(source);
      const first = await ask(asVisited(source));
      if (rule?.kind !== "moved") {
        if (first.status !== 410)
          wrong.push(`${source}: ${first.status}, not 410`);
        return;
      }
      if (first.status !== 308 || pathOf(first.location) !== rule.to) {
        wrong.push(
          `${source}: ${first.status} → ${first.location}, not 308 → ${rule.to}`,
        );
        return;
      }
      // The page, not another redirect and not the page's own 404.
      const second = await ask(rule.to);
      if (second.status !== 200) {
        wrong.push(`${source} → ${rule.to}: ${second.status}, not a page`);
      }
    });

    expect(wrong.slice(0, 40), `${wrong.length} old addresses`).toEqual([]);
  }, 600_000);

  it("lists in the sitemap only addresses that answer a page", async () => {
    const sitemap = await ask("/sitemap.xml");
    expect(sitemap.status).toBe(200);
    const listed = [...sitemap.body.matchAll(/<loc>([^<]+)<\/loc>/g)].map(
      ([, address]) => pathOf(address ?? "") ?? "/",
    );

    const wrong: string[] = [];
    await each(listed, async (address) => {
      const answer = await ask(address);
      if (answer.status !== 200) wrong.push(`${address}: ${answer.status}`);
    });

    expect(wrong.slice(0, 40), `${wrong.length} sitemap lines`).toEqual([]);
    if (site?.routes.includes("/")) expect(listed.length).toBeGreaterThan(0);
  }, 600_000);

  it("answers the home page in every language that has one", async () => {
    if (!site?.routes.includes("/")) return;

    for (const { locale, path } of site.versions("/")) {
      const home = await ask(path);
      expect(home.status, path).toBe(200);
      expect(home.body, path).toContain(`lang="${locale}"`);
    }
  });
});
