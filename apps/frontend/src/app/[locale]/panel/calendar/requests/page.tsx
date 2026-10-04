import { getServerCurrentOrganization } from "#lib/server-auth";
import { RequestsPanel } from "../../../../../modules/shared/booking/dispatch/requests-panel";

export default async function RequestsPage() {
  return <RequestsPanel organization={await getServerCurrentOrganization()} />;
}
