import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * What the proxy answers for a fixed list of addresses, recorded before a
 * product could bring public pages of its own (ADR-080) and compared on every
 * run since: a deployment whose product declares none must get, address by
 * address, what it got before. The locale middleware is next-intl's real one.
 *
 * The profile is written out here, not read from the rendered one, and the
 * product's slot is not read at all — in a product's repository both are the
 * product's own.
 *
 * `UPDATE_GOLDEN=1` writes the file anew; a change of it is a change of what
 * every product's visitors get and belongs in the commit message.
 */
const GOLDEN = path.resolve(__dirname, "proxy.golden.json");

type Variant = {
  locales: string[];
  features: Record<string, boolean>;
};

/** The shapes the existing profiles have, and the marketing-less one. */
const VARIANTS: Record<string, Variant> = {
  // HoofCare, MedPlano, agro.
  "pl-en": { locales: ["pl", "en"], features: { publicBooking: true } },
  // Business, vps-dev.
  "pl-en-de": {
    locales: ["pl", "en", "de"],
    features: { publicBooking: true },
  },
  // core-only.
  "pl-en, no booking": {
    locales: ["pl", "en"],
    features: { publicBooking: false },
  },
  // A profile that switches the core's marketing off (ADR-077 pkt 4).
  "five languages, no marketing": {
    locales: ["pl", "en", "de", "es", "ru"],
    features: { publicBooking: true, marketingSite: false },
  },
};

const PLATFORM_PATHS = [
  "/",
  "/pl",
  "/pl/",
  "/en",
  "/en/",
  "/de",
  "/de/",
  "/ru",
  "/fr",
  "/EN",
  "/pricing",
  "/pricing/",
  "/pricing?plan=pro",
  "/pricing/?plan=pro",
  "/pl/pricing",
  "/pl/pricing?plan=pro",
  "/en/pricing",
  "/de/pricing",
  "/Pricing",
  "/PL/pricing",
  "/contact",
  "/en/contact",
  "/katalog",
  "/pl/katalog",
  "/en/katalog",
  "/de/katalog",
  "/katalog/mragowo/salon",
  "/katalog/mragowo/salon/",
  "/de/katalog/mragowo/salon",
  "/regulamin",
  "/en/terms",
  "/nie-ma/takiej/strony",
  "/en/no/such/page",
  "/rasy-psow/labrador",
  "/en/dog-breeds/labrador",
  "/product-site",
  "/product-site/breeds/labrador",
  "/en/product-site",
  "/za%C5%BC%C3%B3%C5%82%C4%87",
  "/en/caf%C3%A9",
  "/%E0%A4%A",
  "/login",
  "/pl/login",
  "/en/login",
  "/de/login",
  "/register",
  "/en/register",
  "/onboarding",
  "/password-reset",
  "/reset-password",
  "/verify-email",
  "/panel",
  "/panel/",
  "/pl/panel",
  "/en/panel",
  "/de/panel",
  "/de/panel/settings?tab=team",
  "/panel/sites",
  "/panel/calendar",
  "/en/panel/calendar/day",
  "/settings/security",
  "/en/settings/security",
  "/invitations/abc",
  "/book/salon-anna",
  "/en/book/salon-anna",
  "/de/book/salon-anna",
  "/booking/abc",
  "/en/booking/abc",
  "/documents/regulamin",
  "/field/start",
  "/en/field/visits/1/trim",
  "/sitemap.xml",
  "/robots.txt",
  "/site-renderer",
  "/site-renderer/oferta/",
];

const CUSTOMER_PATHS = [
  "/",
  "/oferta",
  "/oferta/",
  "/en/",
  "/en/blog/wpis/",
  "/pl/oferta/",
  "/panel",
  "/login",
  "/pricing",
  "/rasy-psow/labrador",
  "/stary-adres",
  "/sitemap.xml",
  "/robots.txt",
  "/rss.xml",
  "/en/llms.txt",
  "/site-renderer",
  "/site-renderer/oferta/",
];

/** A visitor with no preference, and one whose browser and cookie have one. */
const VISITORS: Record<string, Record<string, string>> = {
  plain: {},
  "prefers en": {
    "accept-language": "en-GB,en;q=0.9,de;q=0.5",
    cookie: "NEXT_LOCALE=en",
  },
  "behind https": { "x-forwarded-proto": "https" },
};

const HOSTS: Record<string, string[]> = {
  "localhost:8080": PLATFORM_PATHS,
  "platform.example.test": PLATFORM_PATHS,
  "studio.example.test": CUSTOMER_PATHS,
};

const REQUEST = "x-middleware-request-";

/** One line per answer: what a visitor and the page behind the proxy see. */
function describeResponse(response: Response): string {
  const said: string[] = [String(response.status)];
  const header = (name: string) => response.headers.get(name);
  if (header("location")) said.push(`location=${header("location")}`);
  if (header("x-middleware-rewrite")) {
    said.push(`rewrite=${header("x-middleware-rewrite")}`);
  }
  if (header("x-middleware-next")) said.push("next");
  const forwarded: string[] = [];
  response.headers.forEach((value, name) => {
    if (!name.startsWith(REQUEST)) return;
    const key = name.slice(REQUEST.length);
    // The visitor's own headers travel on; only what the proxy says matters.
    if (key.startsWith("x-")) forwarded.push(`${key}=${value}`);
  });
  if (forwarded.length) said.push(`request[${forwarded.sort().join(", ")}]`);
  const cookies = response.headers.getSetCookie();
  if (cookies.length) said.push(`set-cookie[${cookies.join(" | ")}]`);
  if (header("link")) said.push(`link=${header("link")}`);
  return said.join(" ");
}

async function record(variant: Variant): Promise<Record<string, string>> {
  vi.resetModules();
  vi.doMock("./generated/deployment", () => ({
    deployment: {
      schemaVersion: 1,
      id: "golden",
      product: {
        name: "Golden",
        defaultLocale: "pl",
        supportedLocales: variant.locales,
        platformDomain: "platform.example.test",
      },
      modules: ["core.health", "core.identity", "core.organizations"],
      features: variant.features,
      organizationTypes: [],
    },
  }));
  const { default: proxy } = await import("./proxy");
  const answers: Record<string, string> = {};
  for (const [host, paths] of Object.entries(HOSTS)) {
    for (const [visitor, headers] of Object.entries(VISITORS)) {
      for (const address of paths) {
        const key = `${host} | ${visitor} | ${address}`;
        try {
          const response = await proxy(
            new NextRequest(`http://${host.split(":")[0]}${address}`, {
              headers: { host, ...headers },
            }),
          );
          answers[key] = describeResponse(response);
        } catch (error) {
          answers[key] = `throws ${(error as Error).name}`;
        }
      }
    }
  }
  return answers;
}

afterEach(() => {
  vi.doUnmock("./generated/deployment");
  vi.resetModules();
});

describe("the proxy answers what it answered before (ADR-080)", () => {
  it("for every recorded address, on every kind of profile", async () => {
    delete process.env.FRONTEND_CONTROL_HOSTS;
    const answers: Record<string, Record<string, string>> = {};
    for (const [name, variant] of Object.entries(VARIANTS)) {
      answers[name] = await record(variant);
    }
    if (process.env.UPDATE_GOLDEN) {
      writeFileSync(GOLDEN, `${JSON.stringify(answers, null, 2)}\n`);
    }
    const golden = JSON.parse(readFileSync(GOLDEN, "utf8"));
    for (const name of Object.keys(VARIANTS)) {
      expect(answers[name], name).toEqual(golden[name]);
    }
    expect(Object.keys(golden)).toEqual(Object.keys(VARIANTS));
  });
});
