import type { Metadata } from "next";

import { deployment } from "../generated/deployment";

const origin = `https://${deployment.product.platformDomain}`;

/** A marketing path in a locale, without the origin (`pl` has no prefix). */
export function localizedPath(locale: string, path: string): string {
  const clean = path === "/" ? "" : path;
  return locale === "pl" ? clean || "/" : `/${locale}${clean}`;
}

/** The address of a marketing path in a locale (`pl` has no prefix). */
export function localizedUrl(locale: string, path: string): string {
  return `${origin}${localizedPath(locale, path)}`;
}

/** Open Graph's name for a language of the registry. */
export function openGraphLocale(locale: string): string {
  return (
    { pl: "pl_PL", en: "en_GB", de: "de_DE", es: "es_ES", ru: "ru_RU" }[
      locale
    ] ?? locale
  );
}

/**
 * Metadata every marketing page shares: canonical, hreflang for both locales
 * and x-default, and Open Graph. One place, so no page can ship without them.
 */
export function marketingMetadata(args: {
  locale: string;
  path: string;
  title: string;
  description: string;
}): Metadata {
  const url = localizedUrl(args.locale, args.path);
  return {
    title: args.title,
    description: args.description,
    alternates: {
      canonical: url,
      languages: {
        pl: localizedUrl("pl", args.path),
        en: localizedUrl("en", args.path),
        "x-default": localizedUrl("pl", args.path),
      },
    },
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
