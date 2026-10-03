import { getServerCurrentOrganization } from "#lib/server-auth";
import { OccupancyPanel } from "../../../../../modules/shared/booking/occupancy/occupancy-panel";

export default async function OccupancyPage() {
  return <OccupancyPanel organization={await getServerCurrentOrganization()} />;
}
