import { notFound } from "next/navigation";
import { panelAccess } from "#lib/panel-navigation";
import { SeoGscPanel } from "../../../../../modules/shared/seo/gsc-panel";
import { getServerCurrentOrganization } from "#lib/server-auth";

export default async function SearchConsolePage() {
  const organization = await getServerCurrentOrganization();
  if (!panelAccess(organization).modules.includes("shared.seo")) notFound();
  return <SeoGscPanel key={organization?.id ?? "no-organization"} />;
}
