import { notFound } from "next/navigation";

import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { InventoryPanel } from "../../../../modules/shared/inventory";

export default async function InventoryPage() {
  const access = panelAccess(await getServerCurrentOrganization());
  if (!allows(access, { module: "shared.inventory" })) notFound();
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 lg:py-10">
      {/* O dostępie decyduje API; to tylko nie prowadzi panelu w 403. */}
      <InventoryPanel
        canManage={allows(access, { permission: "inventory.manage" })}
        canRead={allows(access, { permission: "inventory.read" })}
      />
    </main>
  );
}
