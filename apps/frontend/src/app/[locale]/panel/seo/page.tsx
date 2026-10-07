import { notFound } from "next/navigation";
import { panelAccess } from "#lib/panel-navigation";
import { SeoAuditsPanel } from "../../../../modules/shared/seo";
import { getServerCurrentOrganization } from "#lib/server-auth";

export default async function SeoAuditsPage() {
  const organization = await getServerCurrentOrganization();
  if (!panelAccess(organization).modules.includes("shared.seo")) notFound();
  return (
    <SeoAuditsPanel
      canManageBilling={organization?.role === "owner"}
      key={organization?.id ?? "no-organization"}
    />
  );
}
