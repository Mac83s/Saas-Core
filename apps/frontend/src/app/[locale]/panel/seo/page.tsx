import { notFound } from "next/navigation";
import { modulesFor } from "#lib/organization-types";
import { SeoAuditsPanel } from "../../../../modules/shared/seo";
import { getServerCurrentOrganization } from "#lib/server-auth";

export default async function SeoAuditsPage() {
  const organization = await getServerCurrentOrganization();
  if (!modulesFor(organization?.organization_type).has("shared.seo"))
    notFound();
  return <SeoAuditsPanel key={organization?.id ?? "no-organization"} />;
}
