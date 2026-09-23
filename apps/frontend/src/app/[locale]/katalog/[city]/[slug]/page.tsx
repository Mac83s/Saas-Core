import { cache } from "react";
import { notFound } from "next/navigation";

import { CatalogProfilePage } from "../../../../../modules/shared/profiles";
import { readCatalogProfileOnServer } from "../../../../../modules/shared/profiles/catalog-server";

// `generateMetadata` and the page both need the record, and the read is
// `no-store`, so without this every crawler hit would fetch it twice.
const load = cache(async (city: string, slug: string) => {
  const profile = await readCatalogProfileOnServer(city, slug);
  // A withdrawn or erased company is gone, not broken.
  if (!profile) notFound();
  return profile;
});

export async function generateMetadata({
  params,
}: {
  params: Promise<{ city: string; slug: string }>;
}) {
  const { city, slug } = await params;
  const profile = await load(city, slug);
  return {
    title: `${profile.display_name} — ${profile.city}`,
    description: profile.headline || undefined,
  };
}

export default async function CatalogEntryPage({
  params,
}: {
  params: Promise<{ city: string; slug: string }>;
}) {
  const { city, slug } = await params;
  const profile = await load(city, slug);
  return (
    <main className="mx-auto min-h-screen w-full max-w-3xl px-4 py-10 sm:px-6">
      <CatalogProfilePage profile={profile} />
    </main>
  );
}
