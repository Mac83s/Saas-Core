import { getServerCurrentOrganization } from "#lib/server-auth";
import { BookingPanel } from "../../../../modules/shared/booking";

export default async function CalendarPage() {
  const organization = await getServerCurrentOrganization();
  return (
    <main className="mx-auto w-full max-w-6xl px-5 py-10">
      <BookingPanel organizationType={organization?.organization_type} />
    </main>
  );
}
