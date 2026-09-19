import { notFound } from "next/navigation";
import { modulesFor } from "#lib/organization-types";
import { SeoAuditsPanel } from "../../../../modules/shared/seo";
import { getServerCurrentOrganization } from "#lib/server-auth";

export default async function SeoAuditsPage() {
  const organization = await getServerCurrentOrganization();
  if (!modulesFor(organization?.organization_type).has("shared.seo"))
    notFound();
  return (
    <main className="mx-auto w-full max-w-7xl px-5 py-10">
      <SeoAuditsPanel key={organization?.id ?? "no-organization"} />
    </main>
  );
}
