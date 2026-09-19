import { notFound } from "next/navigation";

import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { FarmsPanel } from "../../../../modules/shared/farms";

export default async function FarmsPage() {
  const access = panelAccess(await getServerCurrentOrganization());
  if (!allows(access, { module: "shared.farms" })) notFound();
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 lg:py-10">
      {/* The API decides; these only keep the panel from leading to a 403. */}
      <FarmsPanel
        canManage={allows(access, { permission: "farms.manage" })}
        canRead={allows(access, { permission: "farms.read" })}
      />
    </main>
  );
}
