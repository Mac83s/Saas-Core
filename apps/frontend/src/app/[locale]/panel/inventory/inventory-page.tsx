import { notFound } from "next/navigation";

import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import {
  InventoryPanel,
  type InventorySection,
} from "../../../../modules/shared/inventory";

/** Every page of Magazyn (ADR-057): the same guard, the same panel, its own part. */
export async function inventoryPage(section: InventorySection) {
  const access = panelAccess(await getServerCurrentOrganization());
  if (!allows(access, { module: "shared.inventory" })) notFound();
  // O dostępie decyduje API; to tylko nie prowadzi panelu w 403.
  return (
    <InventoryPanel
      canManage={allows(access, { permission: "inventory.manage" })}
      canRead={allows(access, { permission: "inventory.read" })}
      section={section}
    />
  );
}
