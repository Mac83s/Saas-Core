import { readdirSync, readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import en from "../../messages/en.json";
import { panelLocales } from "./routing";

/**
 * The guest pages' texts per content language (TL17). A profile that offers
 * a language beyond the panel's two needs every key the guest pages read in
 * it — and nothing the panel reads: those pages never speak it.
 */
const GUEST_NAMESPACES = [
  "Common",
  "Catalog",
  "PublicBooking",
  "BookingSelfService",
  "Marketing",
] as const;

const repository = path.resolve(__dirname, "../../../..");
const catalogues = path.resolve(__dirname, "../../messages/public");

function keys(value: object, prefix = ""): string[] {
  return Object.entries(value).flatMap(([key, entry]) => {
    const at = prefix ? `${prefix}.${key}` : key;
    return typeof entry === "object" && entry !== null ? keys(entry, at) : [at];
  });
}

function guestKeys(): string[] {
  const core = en as Record<string, object>;
  return GUEST_NAMESPACES.flatMap((namespace) =>
    keys(core[namespace] ?? {}, namespace),
  );
}

function catalogue(locale: string): Record<string, object> | null {
  const file = path.join(catalogues, `${locale}.json`);
  return existsSync(file)
    ? (JSON.parse(readFileSync(file, "utf-8")) as Record<string, object>)
    : null;
}

/** Every profile's content languages beyond the panel's. */
function profileLanguages(): [string, string][] {
  const directory = path.join(repository, "deployments");
  return readdirSync(directory, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => path.join(directory, entry.name, "deployment.json"))
    .filter((file) => existsSync(file))
    .flatMap((file) => {
      const profile = JSON.parse(readFileSync(file, "utf-8")) as {
        id: string;
        product: { supportedLocales: string[] };
      };
      return profile.product.supportedLocales
        .filter(
          (locale) => !(panelLocales as readonly string[]).includes(locale),
        )
        .map((locale) => [profile.id, locale] as [string, string]);
    });
}

describe("guest texts per content language (TL17)", () => {
  it.each(profileLanguages())(
    "profile %s speaks %s on every guest page",
    (_profile, locale) => {
      const texts = catalogue(locale);
      expect(texts, `messages/public/${locale}.json`).not.toBeNull();
      const missing = guestKeys().filter(
        (key) => !keys(texts ?? {}).includes(key),
      );
      expect(missing).toEqual([]);
    },
  );

  it("a guest catalogue holds only keys the panel's English has", () => {
    const known = new Set(keys(en));
    for (const file of readdirSync(catalogues)) {
      const texts = catalogue(file.replace(/\.json$/, "")) ?? {};
      expect(
        keys(texts).filter((key) => !known.has(key)),
        file,
      ).toEqual([]);
    }
  });

  it("German has every guest key and none of the panel's", () => {
    const german = keys(catalogue("de") ?? {});
    expect(guestKeys().filter((key) => !german.includes(key))).toEqual([]);
    expect(
      german.filter(
        (key) =>
          !GUEST_NAMESPACES.some((namespace) =>
            key.startsWith(`${namespace}.`),
          ),
      ),
    ).toEqual([]);
  });
});
