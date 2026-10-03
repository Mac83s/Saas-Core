import type { Metadata } from "next";

import type { CatalogProfile } from "@saas-core/api-client";

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
  profile: CatalogProfile;
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
    "@type": "LocalBusiness",
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
