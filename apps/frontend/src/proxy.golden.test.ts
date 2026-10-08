import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { walk } from "./proxy-corpus";

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
  // No public pages of a product: in a product's repository the slot may
  // declare some, and this record is of a deployment that has none.
  vi.doMock("./product/public-site", () => ({ publicSite: null }));
  vi.doMock("./product/old-addresses", () => ({ oldAddresses: {} }));
  const { default: proxy } = await import("./proxy");
  return walk(proxy);
}

afterEach(() => {
  vi.doUnmock("./generated/deployment");
  vi.doUnmock("./product/public-site");
  vi.doUnmock("./product/old-addresses");
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
