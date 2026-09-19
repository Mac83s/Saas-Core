import { notFound } from "next/navigation";

import { modulesFor } from "#lib/organization-types";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { FarmDetail } from "../../../../../modules/shared/farms";

export default async function FarmPage({
  params,
}: {
  params: Promise<{ farmId: string }>;
}) {
  const [{ farmId }, organization] = await Promise.all([
    params,
    getServerCurrentOrganization(),
  ]);
  if (!modulesFor(organization?.organization_type).has("shared.farms"))
    notFound();
  return (
    <main className="mx-auto w-full max-w-5xl px-5 py-10">
      <FarmDetail farmId={farmId} />
    </main>
  );
}
