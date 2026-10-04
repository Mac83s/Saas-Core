import { notFound } from "next/navigation";

import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { OrderPanel } from "../../../../../modules/shared/commerce";

export default async function OrderPage({
  params,
}: {
  params: Promise<{ orderId: string }>;
}) {
  const { orderId } = await params;
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
  return <OrderPanel orderId={orderId} />;
}
