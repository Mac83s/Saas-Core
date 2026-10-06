import type { Metadata } from "next";

import type { CatalogProfile, CatalogUnitPage } from "@saas-core/api-client";

import { deployment } from "../../../generated/deployment";
import { localizedUrl, openGraphLocale } from "../../../marketing/seo";

/**
 * The catalogue in several languages (TL20). A card page exists at every
 * language address the platform routes, but only the languages the card is
 * whole in are worth indexing: its own, and those with a complete
 * translation. Anywhere else the page shows the card in its own language,
 * says so with `lang`, points canonical at itself and asks not to be indexed
 * — and no other page names it as an alternate.
 */

/** What the pages below need of a card: the card itself, or the company a
 *  unit's page stands under. */
type Card = Pick<
  CatalogProfile,
  | "display_name"
  | "headline"
  | "city"
  | "voivodeship"
  | "contact_address"
  | "contact_phone"
  | "contact_email"
  | "url"
  | "is_external"
  | "locale"
  | "source_locale"
  | "translated_locales"
  | "business_type"
>;

/** The routed languages the card is whole in, in routing order. */
export function cardLanguages(
  profile: Pick<CatalogProfile, "source_locale" | "translated_locales">,
  locales: readonly string[],
): string[] {
  return locales.filter(
    (locale) =>
      locale === profile.source_locale ||
      profile.translated_locales.includes(locale),
  );
}

export function catalogCardMetadata(args: {
  profile: CatalogProfile;
  locale: string;
  locales: readonly string[];
  path: string;
  title: string;
  description: string;
}): Metadata {
  const { profile, locale, path } = args;
  const url = localizedUrl(locale, path);
  const whole = cardLanguages(profile, args.locales);
  const indexed = whole.includes(locale);
  const base = whole.includes(profile.source_locale)
    ? profile.source_locale
    : whole[0];
  return {
    title: args.title,
    description: args.description,
    alternates: {
      canonical: url,
      ...(indexed && base
        ? {
            languages: {
              ...Object.fromEntries(
                whole.map((code) => [code, localizedUrl(code, path)]),
              ),
              "x-default": localizedUrl(base, path),
            },
          }
        : {}),
    },
    ...(indexed ? {} : { robots: { index: false, follow: true } }),
    openGraph: {
      title: args.title,
      description: args.description,
      url,
      siteName: deployment.product.name,
      // The card's language, not the page chrome's: that is what is read.
      locale: openGraphLocale(profile.locale),
      type: "website",
    },
  };
}

/**
 * One identity for the company in every language (TL20): the company site's
 * `#organization` when it has a site, otherwise the card in its own language.
 */
export function catalogCardJsonLd(args: {
  profile: Card;
  locales: readonly string[];
  path: string;
}): Record<string, unknown> {
  const { profile, path } = args;
  const whole = cardLanguages(profile, args.locales);
  const home = profile.is_external
    ? profile.url
    : localizedUrl(
        whole.includes(profile.source_locale)
          ? profile.source_locale
          : (args.locales[0] ?? "pl"),
        path,
      );
  return {
    "@context": "https://schema.org",
    // The subtype is a fact where the company's records state one — it lets
    // units by the night, so it is a lodging business whatever its category
    // (ADR-071 pkt 16) — and the category's otherwise.
    "@type": profile.business_type
      ? ["LocalBusiness", profile.business_type]
      : "LocalBusiness",
    "@id": `${home}#organization`,
    name: profile.display_name,
    ...(profile.headline ? { description: profile.headline } : {}),
    url: home,
    address: {
      "@type": "PostalAddress",
      addressLocality: profile.city,
      ...(profile.voivodeship ? { addressRegion: profile.voivodeship } : {}),
      ...(profile.contact_address
        ? { streetAddress: profile.contact_address }
        : {}),
      addressCountry: "PL",
    },
    ...(profile.contact_phone ? { telephone: profile.contact_phone } : {}),
    ...(profile.contact_email ? { email: profile.contact_email } : {}),
  };
}

/** The routed languages a unit's page is worth indexing in: the one the
 *  company writes in and those the unit has a name of its own in — and only
 *  where the card it stands under is whole as well. */
export function unitLanguages(
  page: CatalogUnitPage,
  locales: readonly string[],
): string[] {
  const own = [page.unit.source_locale, ...page.unit.translated_locales];
  return cardLanguages(page.company, locales).filter((locale) =>
    own.includes(locale),
  );
}

/**
 * A unit's page under a company's card (ADR-072, slice 5h): indexed in the
 * languages the unit and its card are both written in, each naming the
 * others; anywhere else it is shown in the company's own language and kept
 * out of the index, as a card is (TL20).
 */
export function catalogUnitMetadata(args: {
  page: CatalogUnitPage;
  locale: string;
  locales: readonly string[];
  path: string;
  title: string;
  description: string;
}): Metadata {
  const { page, locale, path } = args;
  const url = localizedUrl(locale, path);
  const written = unitLanguages(page, args.locales);
  const indexed = written.includes(locale);
  const base = written.includes(page.unit.source_locale)
    ? page.unit.source_locale
    : written[0];
  const cover = page.unit.photos[0];
  return {
    title: args.title,
    description: args.description,
    alternates: {
      canonical: url,
      ...(indexed && base
        ? {
            languages: {
              ...Object.fromEntries(
                written.map((code) => [code, localizedUrl(code, path)]),
              ),
              "x-default": localizedUrl(base, path),
            },
          }
        : {}),
    },
    ...(indexed ? {} : { robots: { index: false, follow: true } }),
    openGraph: {
      title: args.title,
      description: args.description,
      url,
      siteName: deployment.product.name,
      locale: openGraphLocale(page.unit.locale),
      type: "website",
      ...(cover
        ? {
            images: [
              { url: absoluteUrl(cover.preview_url), alt: page.unit.name },
            ],
          }
        : {}),
    },
  };
}

/** A picture at the platform's own address, for whoever reads the page from
 *  outside it (a shared link, a search engine). */
function absoluteUrl(path: string): string {
  return new URL(path, localizedUrl(deployment.product.defaultLocale, "/"))
    .href;
}

/**
 * The unit's page as one graph: the company — the same node its card and
 * its own site name — and the unit, as the module that books it describes
 * it (`thing`): a place to stay the company provides, or a thing it lets
 * out. A unit with nothing to state leaves the company alone.
 */
export function catalogUnitJsonLd(args: {
  page: CatalogUnitPage;
  locales: readonly string[];
  /** The company's card, the page's own address without the language. */
  cardPath: string;
  path: string;
  locale: string;
}): Record<string, unknown> {
  const { page } = args;
  const { "@context": context, ...company } = catalogCardJsonLd({
    profile: page.company,
    locales: args.locales,
    path: args.cardPath,
  });
  const graph: Record<string, unknown>[] = [company];
  if (page.thing) {
    const url = localizedUrl(args.locale, args.path);
    const organization = { "@id": company["@id"] };
    const offers = (page.thing as { offers?: unknown }).offers;
    const cover = page.unit.photos[0];
    graph.push({
      ...page.thing,
      "@id": `${url}#thing`,
      url,
      // A product has a seller, a place to stay a provider.
      ...(offers && typeof offers === "object"
        ? { offers: { ...offers, seller: organization } }
        : { provider: organization }),
      ...(cover ? { image: absoluteUrl(cover.preview_url) } : {}),
    });
  }
  return { "@context": context, "@graph": graph };
}

/**
 * The listing: hreflang between the languages some card is whole in; a
 * listing in a language nobody speaks yet is shown but not indexed.
 * `speaking` null (the backend did not say): every routed language.
 */
export function catalogListMetadata(args: {
  locale: string;
  locales: readonly string[];
  speaking: readonly string[] | null;
  path: string;
  title: string;
  description: string;
}): Metadata {
  const url = localizedUrl(args.locale, args.path);
  const speaking = args.speaking;
  const spoken = speaking
    ? args.locales.filter((code) => speaking.includes(code))
    : [...args.locales];
  const indexed = spoken.includes(args.locale);
  return {
    title: args.title,
    description: args.description,
    alternates: {
      canonical: url,
      ...(indexed
        ? {
            languages: {
              ...Object.fromEntries(
                spoken.map((code) => [code, localizedUrl(code, args.path)]),
              ),
              "x-default": localizedUrl(spoken[0] ?? args.locale, args.path),
            },
          }
        : {}),
    },
    ...(indexed ? {} : { robots: { index: false, follow: true } }),
    openGraph: {
      title: args.title,
      description: args.description,
      url,
      siteName: deployment.product.name,
      locale: openGraphLocale(args.locale),
      type: "website",
    },
  };
}
