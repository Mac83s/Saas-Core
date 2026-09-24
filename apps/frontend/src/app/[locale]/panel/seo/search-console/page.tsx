import { notFound } from "next/navigation";
import { modulesFor } from "#lib/organization-types";
import { SeoGscPanel } from "../../../../../modules/shared/seo/gsc-panel";
import { getServerCurrentOrganization } from "#lib/server-auth";

export default async function SearchConsolePage() {
  const organization = await getServerCurrentOrganization();
  if (!modulesFor(organization?.organization_type).has("shared.seo"))
    notFound();
  return <SeoGscPanel key={organization?.id ?? "no-organization"} />;
}
