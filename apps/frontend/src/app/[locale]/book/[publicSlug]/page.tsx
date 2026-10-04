import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { getServerPublicBookingLocales } from "#lib/server-auth";
import { deployment } from "../../../../generated/deployment";
import { PublicBookingFlow } from "../../../../modules/shared/booking";

// A booking form is a step, not a page to find; the company's site and its
// card in the catalogue are what search engines should show (ADR-071).
export const metadata: Metadata = { robots: { index: false, follow: true } };

/** What a link to the form may choose ahead of the guest (ADR-072, slice
 *  5d): a block of the company's site sends these names. */
const PRESET = ["offer", "group", "unit", "from", "to", "people"] as const;

export default async function PublicBookingPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string; publicSlug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { locale, publicSlug } = await params;
  // A booking page in a language the company does not offer is not one: the
  // language's own 404 (ADR-071 pkt 21). A company whose languages this
  // product serves none of books in the product's first one, as the API
  // does — its form is that language's page, not a 404 in every language.
  const locales = await getServerPublicBookingLocales(publicSlug);
  const spoken: readonly string[] | null =
    locales?.length === 0 ? [deployment.product.defaultLocale] : locales;
  if (spoken !== null && !spoken.includes(locale)) notFound();
  const query = await searchParams;
  const preset = Object.fromEntries(
    PRESET.flatMap((name) =>
      typeof query[name] === "string" ? [[name, query[name]]] : [],
    ),
  );
  return (
    <main className="mx-auto min-h-screen max-w-xl px-5 py-12">
      <PublicBookingFlow preset={preset} publicSlug={publicSlug} />
    </main>
  );
}
