import { getServerCurrentOrganization } from "#lib/server-auth";
import { QueuePanel } from "../../../../../modules/shared/booking/dispatch/queue-panel";

export default async function QueuePage() {
  return <QueuePanel organization={await getServerCurrentOrganization()} />;
}
