import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization, getServerUser } from "#lib/server-auth";
import { BookingPanel } from "../../../../modules/shared/booking";

export default async function CalendarPage() {
  const [organization, user] = await Promise.all([
    getServerCurrentOrganization(),
    getServerUser(),
  ]);
  const access = panelAccess(organization);
  return (
    <BookingPanel
      // What a product's section may offer this person (ADR-067).
      access={access}
      // The API decides; this only keeps actions out of sight of those who
      // may not take them.
      canManage={allows(access, {
        permission: "booking.appointment.manage",
      })}
      canUseInventory={allows(access, {
        module: "shared.inventory",
        permission: "inventory.use",
      })}
      timeZone={organization?.timezone}
      // The view each person last chose, per device (answer 1C, 29.09).
      viewKey={user?.id}
    />
  );
}
