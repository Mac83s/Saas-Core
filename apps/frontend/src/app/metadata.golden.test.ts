import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * The platform host's sitemap and robots, recorded before a product could
 * add entries of its own (ADR-080): a deployment whose product declares no
 * public pages must list what it listed before. The profile and the slot are
 * written out here — in a product's repository both are the product's own.
 *
 * `UPDATE_GOLDEN=1` writes the file anew.
 */
const GOLDEN = path.resolve(__dirname, "metadata.golden.json");

type Variant = {
  locales: string[];
  modules: string[];
  features: Record<string, boolean>;
};

const VARIANTS: Record<string, Variant> = {
  "pl-en with the catalogue": {
    locales: ["pl", "en"],
    modules: ["core.health", "shared.profiles"],
    features: { publicBooking: true },
  },
  "pl-en-de with the catalogue": {
    locales: ["pl", "en", "de"],
    modules: ["core.health", "shared.profiles"],
    features: { publicBooking: true },
  },
  "pl-en without the catalogue": {
    locales: ["pl", "en"],
    modules: ["core.health"],
    features: { publicBooking: false },
  },
  "five languages, no marketing": {
    locales: ["pl", "en", "de", "es", "ru"],
    modules: ["core.health", "shared.profiles"],
    features: { publicBooking: true, marketingSite: false },
  },
};

async function record(variant: Variant) {
  vi.resetModules();
  vi.doMock("../generated/deployment", () => ({
    deployment: {
      schemaVersion: 1,
      id: "golden",
      product: {
        name: "Golden",
        defaultLocale: "pl",
        supportedLocales: variant.locales,
        platformDomain: "platform.example.test",
      },
      modules: variant.modules,
      features: variant.features,
      organizationTypes: [],
    },
  }));
  vi.doMock("../product", () => ({ product: {} }));
  vi.doMock("../product/public-site", () => ({ publicSite: null }));
  vi.doMock("../modules/shared/profiles/catalog-server", () => ({
    readCatalogLocalesOnServer: async () => ["pl", "en"],
    readCatalogSitemapOnServer: async () => [
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
    ],
  }));
  const { default: sitemap } = await import("./sitemap");
  const { default: robots } = await import("./robots");
  return { sitemap: await sitemap(), robots: robots() };
}

afterEach(() => {
  vi.doUnmock("../generated/deployment");
  vi.doUnmock("../product");
  vi.doUnmock("../product/public-site");
  vi.doUnmock("../modules/shared/profiles/catalog-server");
  vi.resetModules();
});

describe("the platform's sitemap and robots say what they said before (ADR-080)", () => {
  it("on every kind of profile", async () => {
    const answers: Record<string, unknown> = {};
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
