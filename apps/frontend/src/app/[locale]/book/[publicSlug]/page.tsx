import { PublicBookingFlow } from "../../../../modules/shared/booking";

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
