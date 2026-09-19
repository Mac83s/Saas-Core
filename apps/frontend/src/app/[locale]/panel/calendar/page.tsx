import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { BookingPanel } from "../../../../modules/shared/booking";

export default async function CalendarPage() {
  const organization = await getServerCurrentOrganization();
  return (
    <main className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:py-10">
      <BookingPanel
        // The API decides; this only keeps actions out of sight of those who
        // may not take them.
        canManage={allows(panelAccess(organization), {
          permission: "booking.appointment.manage",
        })}
        timeZone={organization?.timezone}
      />
    </main>
  );
}
