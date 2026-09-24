import { SitesPanel } from "../../../../modules/shared/sites";
import { getServerCurrentOrganization } from "#lib/server-auth";

export default async function SitesPage() {
  const organization = await getServerCurrentOrganization();
  return (
    <SitesPanel
      key={organization?.id ?? "no-organization"}
      canManageBilling={organization?.role === "owner"}
    />
  );
}
