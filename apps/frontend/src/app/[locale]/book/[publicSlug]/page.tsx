import type { Metadata } from "next";

import { PublicBookingFlow } from "../../../../modules/shared/booking";

// A booking form is a step, not a page to find; the company's site and its
// card in the catalogue are what search engines should show (ADR-071).
export const metadata: Metadata = { robots: { index: false, follow: true } };

export default async function PublicBookingPage({
  params,
}: {
  params: Promise<{ publicSlug: string }>;
}) {
  const { publicSlug } = await params;
  return (
    <main className="mx-auto min-h-screen max-w-xl px-5 py-12">
      <PublicBookingFlow publicSlug={publicSlug} />
    </main>
  );
}
