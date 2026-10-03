import type { Metadata } from "next";
import { cache } from "react";
import { notFound } from "next/navigation";

import { routing } from "#i18n/routing";
import {
  productHasCatalog,
  productName,
} from "../../../../../../marketing/content";
import { CatalogProfilePage } from "../../../../../../modules/shared/profiles";
import {
  catalogCardJsonLd,
  catalogCardMetadata,
} from "../../../../../../modules/shared/profiles/catalog-seo";
import { readCatalogProfileOnServer } from "../../../../../../modules/shared/profiles/catalog-server";
import { JsonLd } from "#components/json-ld";

type Props = {
  params: Promise<{ locale: string; city: string; slug: string }>;
};

// `generateMetadata` and the page both need the record, and the read is
// `no-store`, so without this every crawler hit would fetch it twice.
const load = cache(async (city: string, slug: string, locale: string) => {
  if (!productHasCatalog) notFound();
  const profile = await readCatalogProfileOnServer(city, slug, locale);
  // A withdrawn or erased company is gone, not broken.
  if (!profile) notFound();
  return profile;
});

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, city, slug } = await params;
  const profile = await load(city, slug, locale);
  return catalogCardMetadata({
    profile,
    locale,
    locales: routing.locales,
    path: `/katalog/${city}/${slug}`,
    title: `${profile.display_name} — ${profile.city} — ${productName}`,
    // Not one shared intro: entries without a headline would all read alike.
    description: profile.headline || `${profile.display_name}, ${profile.city}`,
  });
}

export default async function CatalogEntryPage({ params }: Props) {
  const { locale, city, slug } = await params;
  const profile = await load(city, slug, locale);
  const identity = catalogCardJsonLd({
    profile,
    locales: routing.locales,
    path: `/katalog/${city}/${slug}`,
  });
  return (
    // The card's own language where it is not translated: the page says so
    // rather than letting the chrome's `lang` claim its text (TL20).
    <section
      className="mx-auto w-full max-w-3xl px-5 py-12 sm:py-16"
      lang={profile.locale}
    >
      {/* A company's text: printed only through `JsonLd`. */}
      <JsonLd data={identity} />
      <CatalogProfilePage profile={profile} />
    </section>
  );
}
