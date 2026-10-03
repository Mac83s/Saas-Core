import { describe, expect, it } from "vitest";

import type { CatalogProfile } from "@saas-core/api-client";

import { deployment } from "../../../generated/deployment";
import {
  catalogCardJsonLd,
  catalogCardMetadata,
  catalogListMetadata,
} from "./catalog-seo";

const origin = `https://${deployment.product.platformDomain}`;
const PATH = "/katalog/mragowo/salon";
const LOCALES = ["pl", "en"] as const;

function card(overrides: Partial<CatalogProfile> = {}): CatalogProfile {
  return {
    slug: "salon",
    city_slug: "mragowo",
    city: "Mrągowo",
    category: "uroda-i-zdrowie",
    display_name: "Salon Anna",
    headline: "Fryzjer",
    photo_id: null,
    url: "/katalog/mragowo/salon/",
    is_external: false,
    distance_km: null,
    locale: "pl",
    source_locale: "pl",
    translated_locales: [],
    fallback: [],
    layout: "card",
    voivodeship: "warmińsko-mazurskie",
    bio: "",
    contact_email: "",
    contact_phone: "+48 600 100 200",
    contact_address: "",
    links: [],
    languages: [],
    specializations: [],
    ...overrides,
  };
}

function metadata(profile: CatalogProfile, locale: string) {
  return catalogCardMetadata({
    profile,
    locale,
    locales: LOCALES,
    path: PATH,
    title: "t",
    description: "d",
  });
}

describe("catalogue card per language (TL20)", () => {
  it("a card translated into English is indexed in both, each naming the other", () => {
    const english = metadata(
      card({ locale: "en", translated_locales: ["en"] }),
      "en",
    );

    expect(english.alternates?.canonical).toBe(`${origin}/en${PATH}`);
    expect(english.alternates?.languages).toEqual({
      pl: `${origin}${PATH}`,
      en: `${origin}/en${PATH}`,
      "x-default": `${origin}${PATH}`,
    });
    expect(english.robots).toBeUndefined();
    expect(english.openGraph).toMatchObject({ locale: "en_GB" });
  });

  it("an untranslated card in English points at itself, is not indexed, names no alternates", () => {
    const english = metadata(card(), "en");

    expect(english.alternates?.canonical).toBe(`${origin}/en${PATH}`);
    expect(english.alternates?.languages).toBeUndefined();
    expect(english.robots).toEqual({ index: false, follow: true });
    // What is read there is the Polish card.
    expect(english.openGraph).toMatchObject({ locale: "pl_PL" });
  });

  it("a language the company switched off is named nowhere", () => {
    // The row's copy dropped `en` when the company switched it off.
    const polish = metadata(card({ translated_locales: [] }), "pl");

    expect(polish.alternates?.languages).toEqual({
      pl: `${origin}${PATH}`,
      "x-default": `${origin}${PATH}`,
    });
    expect(JSON.stringify(polish)).not.toContain(`${origin}/en`);
  });

  it("a translation in a language the platform does not route yet is not an alternate", () => {
    const polish = metadata(card({ translated_locales: ["de"] }), "pl");

    expect(Object.keys(polish.alternates?.languages ?? {})).toEqual([
      "pl",
      "x-default",
    ]);
  });

  it("one identity in every language: the company's site, or the card in its own", () => {
    const withSite = catalogCardJsonLd({
      profile: card({ is_external: true, url: "https://salon-anna.pl/" }),
      locales: LOCALES,
      path: PATH,
    });
    const without = catalogCardJsonLd({
      profile: card({ locale: "en", translated_locales: ["en"] }),
      locales: LOCALES,
      path: PATH,
    });

    expect(withSite["@id"]).toBe("https://salon-anna.pl/#organization");
    expect(without["@id"]).toBe(`${origin}${PATH}#organization`);
    expect(without).toMatchObject({
      "@type": "LocalBusiness",
      name: "Salon Anna",
      telephone: "+48 600 100 200",
    });
  });
});

describe("catalogue listing per language (TL20)", () => {
  function list(locale: string, speaking: string[] | null) {
    return catalogListMetadata({
      locale,
      locales: LOCALES,
      speaking,
      path: "/katalog",
      title: "t",
      description: "d",
    });
  }

  it("a listing in a language no card speaks is shown but not indexed", () => {
    const english = list("en", ["pl"]);

    expect(english.robots).toEqual({ index: false, follow: true });
    expect(english.alternates?.languages).toBeUndefined();
    expect(list("pl", ["pl"]).alternates?.languages).toEqual({
      pl: `${origin}/katalog`,
      "x-default": `${origin}/katalog`,
    });
  });

  it("unknown languages (backend silent) keep every routed listing indexed", () => {
    const english = list("en", null);

    expect(english.robots).toBeUndefined();
    expect(english.alternates?.languages).toEqual({
      pl: `${origin}/katalog`,
      en: `${origin}/en/katalog`,
      "x-default": `${origin}/katalog`,
    });
  });
});
