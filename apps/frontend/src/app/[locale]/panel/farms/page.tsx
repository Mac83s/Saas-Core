import { notFound } from "next/navigation";

import { modulesFor } from "#lib/organization-types";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { FarmsPanel } from "../../../../modules/shared/farms";

export default async function FarmsPage() {
  const organization = await getServerCurrentOrganization();
  if (!modulesFor(organization?.organization_type).has("shared.farms"))
    notFound();
  return (
    <main className="mx-auto w-full max-w-5xl px-5 py-10">
      <FarmsPanel />
    </main>
  );
}
