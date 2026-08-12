import { SelfServiceBooking } from "../../../../modules/shared/booking";

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
