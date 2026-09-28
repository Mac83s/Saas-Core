import { getServerCurrentOrganization } from "#lib/server-auth";
import { TeamsPanel } from "../../../../../modules/shared/booking/teams/teams-panel";

export default async function TeamsPage() {
  return <TeamsPanel organization={await getServerCurrentOrganization()} />;
}
