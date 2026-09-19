import { SitesPanel } from "../../../../modules/shared/sites";
import { getServerCurrentOrganization } from "#lib/server-auth";

export default async function SitesPage() {
  const organization = await getServerCurrentOrganization();
  return (
    <main className="mx-auto w-full max-w-7xl px-5 py-10">
      <SitesPanel
        key={organization?.id ?? "no-organization"}
        canManageBilling={organization?.role === "owner"}
      />
    </main>
  );
}
