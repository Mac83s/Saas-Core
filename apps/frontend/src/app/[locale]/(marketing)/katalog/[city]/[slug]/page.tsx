import type { Metadata } from "next";
import { cache } from "react";
import { notFound } from "next/navigation";

import {
  productHasCatalog,
  productName,
} from "../../../../../../marketing/content";
import { marketingMetadata } from "../../../../../../marketing/seo";
import { CatalogProfilePage } from "../../../../../../modules/shared/profiles";
import { readCatalogProfileOnServer } from "../../../../../../modules/shared/profiles/catalog-server";

type Props = {
  params: Promise<{ locale: string; city: string; slug: string }>;
};

// `generateMetadata` and the page both need the record, and the read is
// `no-store`, so without this every crawler hit would fetch it twice.
const load = cache(async (city: string, slug: string) => {
  if (!productHasCatalog) notFound();
  const profile = await readCatalogProfileOnServer(city, slug);
  // A withdrawn or erased company is gone, not broken.
  if (!profile) notFound();
  return profile;
});

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, city, slug } = await params;
  const profile = await load(city, slug);
  return marketingMetadata({
    locale,
    path: `/katalog/${city}/${slug}`,
    title: `${profile.display_name} — ${profile.city} — ${productName}`,
    // Not one shared intro: entries without a headline would all read alike.
    description: profile.headline || `${profile.display_name}, ${profile.city}`,
  });
}

export default async function CatalogEntryPage({ params }: Props) {
  const { city, slug } = await params;
  const profile = await load(city, slug);
  return (
    <section className="mx-auto w-full max-w-3xl px-5 py-12 sm:py-16">
      <CatalogProfilePage profile={profile} />
    </section>
  );
}
