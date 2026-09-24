import { notFound } from "next/navigation";

import { allows, panelAccess } from "#lib/panel-navigation";
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
  const access = panelAccess(organization);
  if (!allows(access, { module: "shared.farms" })) notFound();
  // The API decides; these only keep the panel from leading to a 403.
  return (
    <FarmDetail
      canManage={allows(access, { permission: "farms.manage" })}
      canRead={allows(access, { permission: "farms.read" })}
      access={access}
      farmId={farmId}
    />
  );
}
