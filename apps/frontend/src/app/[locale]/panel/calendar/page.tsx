import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { BookingPanel } from "../../../../modules/shared/booking";

export default async function CalendarPage() {
  const organization = await getServerCurrentOrganization();
  return (
    <BookingPanel
      // The API decides; this only keeps actions out of sight of those who
      // may not take them.
      canManage={allows(panelAccess(organization), {
        permission: "booking.appointment.manage",
      })}
      canUseInventory={allows(panelAccess(organization), {
        module: "shared.inventory",
        permission: "inventory.use",
      })}
      timeZone={organization?.timezone}
    />
  );
}
