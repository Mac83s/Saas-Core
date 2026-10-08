import type {
  ProductOldAddresses,
  ProductPublicSite,
  SiteSitemapEntry,
} from "#lib/product-site";

/**
 * A product's public pages as a product would declare them — for tests only
 * (ADR-080). No product is named: a content site with a home page, a section
 * named per language, a page some languages lack, and the old addresses of
 * the site it replaced.
 */
export const fixtureSite: ProductPublicSite = {
  routes: {
    "/": "/",
    "/breeds": { pl: "/rasy-psow", en: "/dog-breeds", de: "/hunderassen" },
    "/breeds/[slug]": {
      pl: "/rasy-psow/[slug]",
      en: "/dog-breeds/[slug]",
      de: "/hunderassen/[slug]",
    },
    "/breeds/compare": { pl: "/rasy-psow/porownaj", en: "/dog-breeds/compare" },
    "/quiz": "/quiz",
    "/guide/[chapter]": { pl: "/poradnik/[chapter]" },
  },
};

export const fixtureOldAddresses: ProductOldAddresses = {
  moved: {
    "/rasy/labrador-retriever": "/rasy-psow/labrador",
    "/en/breeds/Labrador-Retriever/": "/en/dog-breeds/labrador",
    // An entry renamed inside its section: the rule lies over the section's
    // own address pattern, which is the point.
    "/rasy-psow/owczarek": "/rasy-psow/owczarek-niemiecki",
    "/Poradnik/Żywienie szczeniaka": "/poradnik/zywienie",
  },
  gone: ["/sklep", "/en/shop/old-offer", "/de/laden"],
};

export const fixtureSitemap: SiteSitemapEntry[] = [
  { route: "/" },
  { route: "/breeds" },
  { route: "/quiz" },
  {
    route: "/breeds/[slug]",
    // The entry's own name is translated; Spanish and Russian have no page.
    params: {
      pl: { slug: "owczarek-niemiecki" },
      en: { slug: "german-shepherd" },
      de: { slug: "deutscher-schaeferhund" },
    },
    lastModified: "2026-10-08T08:00:00Z",
  },
  // Still listed by the product, but redirected since: must not be a line.
  { route: "/breeds/[slug]", params: { pl: { slug: "owczarek" } } },
  { route: "/guide/[chapter]", params: { chapter: "zywienie" } },
];

/** The profile the fixture is served by: five languages, no core marketing. */
export function fixtureDeployment(
  features: Record<string, boolean> = {},
  locales: string[] = ["pl", "en", "de", "es", "ru"],
) {
  return {
    schemaVersion: 1,
    id: "fixture",
    product: {
      name: "Fixture",
      defaultLocale: "pl",
      supportedLocales: locales,
      platformDomain: "platform.example.test",
    },
    modules: ["core.health", "core.identity", "core.organizations"],
    features: { publicBooking: true, marketingSite: false, ...features },
    organizationTypes: [],
  };
}
