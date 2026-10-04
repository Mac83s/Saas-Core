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
  const access = organization ? panelAccess(organization) : undefined;
  if (
    !access ||
    !allows(access, {
      module: "shared.commerce",
      permission: "commerce.orders.read",
    })
  ) {
    notFound();
  }
  return (
    <OrderPanel
      canManagePayments={allows(access, {
        module: "shared.commerce",
        permission: "commerce.payments.manage",
      })}
      orderId={orderId}
    />
  );
}
