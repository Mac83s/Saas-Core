import { describe, expect, it } from "vitest";

import type { CatalogProfile, CatalogUnitPage } from "@saas-core/api-client";

import { deployment } from "../../../generated/deployment";
import {
  catalogCardJsonLd,
  catalogCardMetadata,
  catalogListMetadata,
  catalogUnitJsonLd,
  catalogUnitMetadata,
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
    badges: [],
    business_type: "",
    booking: null,
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

describe("what the company is, and a unit's page under its card (5h)", () => {
  const UNIT_PATH = `${PATH}/domek-sosnowy`;

  function unitPage(
    overrides: Partial<CatalogUnitPage["unit"]> = {},
    company: Partial<CatalogProfile> = {},
    thing: CatalogUnitPage["thing"] = {
      "@type": "Accommodation",
      name: "Domek Sosnowy",
    },
  ): CatalogUnitPage {
    return {
      // The card the page stands under (what it lists besides is not read).
      company: card({
        display_name: "Domki nad Jeziorem",
        business_type: "LodgingBusiness",
        ...company,
      }),
      booking: {
        form_url: `${origin}/book/domki`,
        form_slug: "domki",
        timezone: "Europe/Warsaw",
        last_day: "2027-10-06",
        paused: false,
        origin: "token",
      },
      unit: {
        slug: "domek-sosnowy",
        name: "Domek Sosnowy",
        description: "Nad samym jeziorem.",
        capacity: 6,
        photos: [
          {
            id: "0199a000-0000-7000-8000-000000000001",
            thumbnail_url: "/api/v1/booking/public/domki/photos/1/thumbnail/",
            preview_url: "/api/v1/booking/public/domki/photos/1/preview/",
            width: 1600,
            height: 1200,
            ai_generated: false,
          },
        ],
        amenities: [],
        town: { slug: "mragowo", name: "Mrągowo" },
        from_price: null,
        locale: "pl",
        source_locale: "pl",
        translated_locales: [],
        ...overrides,
      },
      offers: [],
      thing,
    };
  }

  it("a company that lets units by the night is a LodgingBusiness on its card", () => {
    const lodging = catalogCardJsonLd({
      profile: card({ business_type: "LodgingBusiness" }),
      locales: LOCALES,
      path: PATH,
    });

    expect(lodging["@type"]).toEqual(["LocalBusiness", "LodgingBusiness"]);
  });

  it("the unit's graph names the company's node as the provider of the stay", () => {
    const data = catalogUnitJsonLd({
      page: unitPage(),
      locales: LOCALES,
      cardPath: PATH,
      path: UNIT_PATH,
      locale: "pl",
    });
    const [company, unit] = data["@graph"] as Record<string, unknown>[];

    expect(company).toMatchObject({
      "@type": ["LocalBusiness", "LodgingBusiness"],
      "@id": `${origin}${PATH}#organization`,
    });
    expect(unit).toMatchObject({
      "@type": "Accommodation",
      "@id": `${origin}${UNIT_PATH}#thing`,
      url: `${origin}${UNIT_PATH}`,
      provider: { "@id": `${origin}${PATH}#organization` },
      image: `${origin}/api/v1/booking/public/domki/photos/1/preview/`,
    });
  });

  it("a thing let by the day is a product the company sells the hire of", () => {
    const data = catalogUnitJsonLd({
      page: unitPage(
        {},
        { is_external: true, url: "https://kajaki.pl/" },
        {
          "@type": "Product",
          name: "Kajak",
          offers: { "@type": "Offer" },
        },
      ),
      locales: LOCALES,
      cardPath: PATH,
      path: UNIT_PATH,
      locale: "pl",
    });
    const [, unit] = data["@graph"] as Record<string, unknown>[];

    // The company's own site is its one identity (TL18).
    expect(unit!.offers).toEqual({
      "@type": "Offer",
      seller: { "@id": "https://kajaki.pl/#organization" },
    });
    expect(unit).not.toHaveProperty("provider");
  });

  it("a unit with nothing to state leaves the company alone in the graph", () => {
    const data = catalogUnitJsonLd({
      page: unitPage({}, {}, null),
      locales: LOCALES,
      cardPath: PATH,
      path: UNIT_PATH,
      locale: "pl",
    });

    expect(data["@graph"]).toHaveLength(1);
  });

  it("the page is indexed where the unit and its card are both written", () => {
    const args = {
      locales: LOCALES,
      path: UNIT_PATH,
      title: "t",
      description: "d",
    };
    const polish = catalogUnitMetadata({
      ...args,
      page: unitPage(),
      locale: "pl",
    });
    const english = catalogUnitMetadata({
      ...args,
      page: unitPage(),
      locale: "en",
    });
    // The unit has an English name, the card it stands under does not.
    const half = catalogUnitMetadata({
      ...args,
      page: unitPage({ translated_locales: ["en"] }),
      locale: "en",
    });
    const both = catalogUnitMetadata({
      ...args,
      page: unitPage(
        { locale: "en", translated_locales: ["en"] },
        { translated_locales: ["en"] },
      ),
      locale: "en",
    });

    expect(polish.robots).toBeUndefined();
    expect(polish.alternates?.languages).toEqual({
      pl: `${origin}${UNIT_PATH}`,
      "x-default": `${origin}${UNIT_PATH}`,
    });
    expect(polish.openGraph?.images).toEqual([
      {
        url: `${origin}/api/v1/booking/public/domki/photos/1/preview/`,
        alt: "Domek Sosnowy",
      },
    ]);
    expect(english.robots).toEqual({ index: false, follow: true });
    expect(english.alternates?.languages).toBeUndefined();
    expect(half.robots).toEqual({ index: false, follow: true });
    expect(both.robots).toBeUndefined();
    expect(both.alternates?.languages).toEqual({
      pl: `${origin}${UNIT_PATH}`,
      en: `${origin}/en${UNIT_PATH}`,
      "x-default": `${origin}${UNIT_PATH}`,
    });
  });
});
