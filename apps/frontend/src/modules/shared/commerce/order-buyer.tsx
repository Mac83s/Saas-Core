"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { type Order } from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";

import { formatDate } from "#lib/dates";

import { RemoveCustomerDialog } from "../customers/remove-customer-dialog";

/**
 * What the order page says about its buyer's data (ADR-073, slice 4i): for
 * an anonymised customer, whether the order still names its buyer and until
 * which day; for a named one, the way to remove the person — the question
 * every such place of the panel asks (`RemoveCustomerDialog`). The days and
 * the reasons are the server's; nothing about the period is worked out here.
 */
export function OrderBuyerPrivacy({
  canAnonymize,
  onAnonymized,
  order,
}: {
  /** May anonymise a customer (`booking.appointment.manage`). */
  canAnonymize: boolean;
  /** The customer is gone: the page reads the order again. */
  onAnonymized: (notice: string) => void;
  order: Order;
}) {
  const t = useTranslations("Orders");
  const locale = useLocale();
  const [asking, setAsking] = useState(false);

  if (order.customer_anonymized_at) {
    return (
      <p className="border-t pt-2 text-muted-foreground">
        {order.buyer_kept_until
          ? t("buyerKept", {
              date: formatDate(order.customer_anonymized_at, locale),
              until: formatDate(order.buyer_kept_until, locale),
            })
          : t("buyerRemoved", {
              date: formatDate(order.customer_anonymized_at, locale),
            })}
      </p>
    );
  }
  if (!canAnonymize) return null;
  return (
    <div className="border-t pt-2">
      <Button
        onClick={() => setAsking(true)}
        size="sm"
        type="button"
        variant="outline"
      >
        {t("anonymize")}
      </Button>
      {asking ? (
        <RemoveCustomerDialog
          customerId={order.customer_id}
          name={order.buyer_name}
          onDone={() => {
            setAsking(false);
            onAnonymized(t("anonymized"));
          }}
          onOpenChange={setAsking}
        />
      ) : null}
    </div>
  );
}
