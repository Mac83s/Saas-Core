import { notFound } from "next/navigation";

import { allows, panelAccess, profileOffers } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { OrderPanel } from "../../../../../modules/shared/commerce";

/**
 * Removing a customer's data by hand is offered where the profile offers
 * their removal after a time (`features.customerRetention`): in a product
 * whose visit hangs on another record of the same person — a farm's card —
 * the customer would stay named there, and the window would promise more
 * than happens (docs/architecture/privacy-retention.md).
 */
const customerRemovalOffered = profileOffers("customerRetention");

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
      canAnonymize={
        customerRemovalOffered &&
        allows(access, {
          module: "shared.booking",
          permission: "booking.appointment.manage",
        })
      }
      canManagePayments={allows(access, {
        module: "shared.commerce",
        permission: "commerce.payments.manage",
      })}
      orderId={orderId}
    />
  );
}
