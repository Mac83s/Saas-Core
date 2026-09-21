import { cache } from "react";
import { notFound } from "next/navigation";

import { ApiProblemError, readCatalogProfile } from "@saas-core/api-client";

import { CatalogProfilePage } from "../../../../../modules/shared/profiles";

// `generateMetadata` and the page both need the record, and the client reads
// with `no-store`, so without this every crawler hit would fetch it twice.
const load = cache(async (city: string, slug: string) => {
  try {
    return await readCatalogProfile(city, slug);
  } catch (error) {
    // A withdrawn or erased company is gone, not broken.
    if (error instanceof ApiProblemError && error.problem.status === 404) {
      notFound();
    }
    throw error;
  }
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
