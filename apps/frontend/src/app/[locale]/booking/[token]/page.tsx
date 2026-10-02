import type { Metadata } from "next";

import { SelfServiceBooking } from "../../../../modules/shared/booking";

// The address carries the customer's own token: never indexed, and never sent
// on as a Referer to whatever the page links to (ADR-071).
export const metadata: Metadata = {
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default async function SelfServiceBookingPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return (
    <main className="mx-auto min-h-screen max-w-xl px-5 py-12">
      <SelfServiceBooking token={token} />
    </main>
  );
}
