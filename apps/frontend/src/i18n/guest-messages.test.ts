import { readdirSync, readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import en from "../../messages/en.json";
import { panelLocales } from "./routing";

type Profile = {
  id: string;
  product: { supportedLocales: string[] };
  modules: string[];
  features?: Record<string, boolean | undefined>;
};

const has = (profile: Profile, module: string) =>
  profile.modules.includes(module);
/** `features.marketingSite`: on unless the profile says `false` (ADR-077). */
const marketing = (profile: Profile) =>
  profile.features?.marketingSite !== false;

/**
 * The guest pages' texts per content language (TL17). A profile that offers
 * a language beyond the panel's two needs every key the guest pages it
 * serves read in it — and nothing the panel reads: those pages never speak
 * it.
 *
 * Which guest pages a profile serves follows its composition, as the routes
 * themselves do: the booking form, a visit's own page and their prices are
 * `shared.booking`'s; a company's document is `shared.customers`' and is
 * named in the booking form too; the catalogue is `shared.profiles`' on a
 * host that shows marketing (`productHasCatalog`), under the marketing
 * header and footer. A profile that composes none of them — a product whose
 * public site is built in the site builder — owes its languages only the
 * words every page shares.
 */
const GUEST_PAGES: Record<string, (profile: Profile) => boolean> = {
  Common: () => true,
  Catalog: (profile) => marketing(profile) && has(profile, "shared.profiles"),
  PublicBooking: (profile) => has(profile, "shared.booking"),
  BookingSelfService: (profile) => has(profile, "shared.booking"),
  BookingPrice: (profile) => has(profile, "shared.booking"),
  Marketing: marketing,
  CustomerDocument: (profile) =>
    has(profile, "shared.customers") || has(profile, "shared.booking"),
};
const GUEST_NAMESPACES = Object.keys(GUEST_PAGES);

/** The namespaces of the guest pages a profile serves. */
function servedNamespaces(profile: Profile): string[] {
  return GUEST_NAMESPACES.filter((namespace) =>
    GUEST_PAGES[namespace](profile),
  );
}

const repository = path.resolve(__dirname, "../../../..");
const catalogues = path.resolve(__dirname, "../../messages/public");

function keys(value: object, prefix = ""): string[] {
  return Object.entries(value).flatMap(([key, entry]) => {
    const at = prefix ? `${prefix}.${key}` : key;
    return typeof entry === "object" && entry !== null ? keys(entry, at) : [at];
  });
}

function guestKeys(namespaces: readonly string[] = GUEST_NAMESPACES): string[] {
  const core = en as Record<string, object>;
  return namespaces.flatMap((namespace) =>
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
function profileLanguages(): [string, string, Profile][] {
  const directory = path.join(repository, "deployments");
  return readdirSync(directory, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => path.join(directory, entry.name, "deployment.json"))
    .filter((file) => existsSync(file))
    .flatMap((file) => {
      const profile = JSON.parse(readFileSync(file, "utf-8")) as Profile;
      return profile.product.supportedLocales
        .filter(
          (locale) => !(panelLocales as readonly string[]).includes(locale),
        )
        .map(
          (locale) =>
            [profile.id, locale, profile] as [string, string, Profile],
        );
    });
}

describe("guest texts per content language (TL17)", () => {
  it.each(profileLanguages())(
    "profile %s speaks %s on every guest page it serves",
    (_id, locale, profile) => {
      const texts = catalogue(locale);
      expect(texts, `messages/public/${locale}.json`).not.toBeNull();
      const missing = guestKeys(servedNamespaces(profile)).filter(
        (key) => !keys(texts ?? {}).includes(key),
      );
      expect(missing).toEqual([]);
    },
  );

  it("a profile is held to the guest pages it composes — all of them where it composes all", () => {
    const profile = (
      modules: string[],
      features: Profile["features"] = {},
    ): Profile => ({
      id: "x",
      product: { supportedLocales: ["pl", "en", "de"] },
      modules,
      features,
    });
    // Business, and every product standing on it: nothing is left out.
    const everything = profile([
      "shared.profiles",
      "shared.customers",
      "shared.booking",
    ]);
    expect(servedNamespaces(everything)).toEqual(GUEST_NAMESPACES);
    expect(guestKeys(servedNamespaces(everything))).toEqual(guestKeys());
    // A content site in the site builder, its platform host the panel only.
    expect(
      servedNamespaces(
        profile(["shared.sites", "shared.translation"], {
          marketingSite: false,
        }),
      ),
    ).toEqual(["Common"]);
    // Each page by its own switch.
    expect(
      servedNamespaces(profile(["shared.profiles"], { marketingSite: false })),
    ).toEqual(["Common"]);
    expect(servedNamespaces(profile(["shared.profiles"]))).toEqual([
      "Common",
      "Catalog",
      "Marketing",
    ]);
    expect(servedNamespaces(profile(["shared.customers"]))).toEqual([
      "Common",
      "Marketing",
      "CustomerDocument",
    ]);
    expect(
      servedNamespaces(profile(["shared.booking"], { marketingSite: false })),
    ).toEqual([
      "Common",
      "PublicBooking",
      "BookingSelfService",
      "BookingPrice",
      "CustomerDocument",
    ]);
  });

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
