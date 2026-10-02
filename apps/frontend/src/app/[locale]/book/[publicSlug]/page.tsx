import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { getServerPublicBookingLocales } from "#lib/server-auth";
import { PublicBookingFlow } from "../../../../modules/shared/booking";

// A booking form is a step, not a page to find; the company's site and its
// card in the catalogue are what search engines should show (ADR-071).
export const metadata: Metadata = { robots: { index: false, follow: true } };

export default async function PublicBookingPage({
  params,
}: {
  params: Promise<{ locale: string; publicSlug: string }>;
}) {
  const { locale, publicSlug } = await params;
  // A booking page in a language the company does not offer is not one: the
  // language's own 404 (ADR-071 pkt 21).
  const locales = await getServerPublicBookingLocales(publicSlug);
  if (locales !== null && !locales.includes(locale)) notFound();
  return (
    <main className="mx-auto min-h-screen max-w-xl px-5 py-12">
      <PublicBookingFlow publicSlug={publicSlug} />
    </main>
  );
}
