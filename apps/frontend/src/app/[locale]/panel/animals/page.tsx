import { notFound } from "next/navigation";

import { modulesFor } from "#lib/organization-types";
import { panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { AnimalsPanel } from "../../../../modules/shared/farms";

export default async function AnimalsPage() {
  const organization = await getServerCurrentOrganization();
  if (!modulesFor(organization?.organization_type).has("shared.farms"))
    notFound();
  return <AnimalsPanel access={panelAccess(organization)} />;
}
