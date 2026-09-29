import { getServerCurrentOrganization } from "#lib/server-auth";
import { PerformancePanel } from "../../../../../modules/shared/booking/people/performance-panel";

export default async function PerformancePage() {
  return (
    <PerformancePanel organization={await getServerCurrentOrganization()} />
  );
}
