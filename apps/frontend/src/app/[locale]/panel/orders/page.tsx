import { notFound } from "next/navigation";

import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { OrdersPanel } from "../../../../modules/shared/commerce";

/** Zamówienia: what the company's customers bought (ADR-073 §3). */
export default async function OrdersPage() {
  const organization = await getServerCurrentOrganization();
  if (
    !organization ||
    !allows(panelAccess(organization), {
      module: "shared.commerce",
      permission: "commerce.orders.read",
    })
  ) {
    notFound();
  }
  return <OrdersPanel canManageBilling={organization.role === "owner"} />;
}
