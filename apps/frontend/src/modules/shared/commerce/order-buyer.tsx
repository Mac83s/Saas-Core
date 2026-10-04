"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import {
  anonymizeCustomer,
  previewCustomerAnonymization,
  type CustomerKept,
  type Order,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";

import { formatDate } from "#lib/dates";

import { refusal } from "./order-payments";

/**
 * What the order page says about its buyer's data (ADR-073, slice 4i): for
 * an anonymised customer, whether the order still names its buyer and until
 * which day; for a named one, the way to remove the person — with what stays
 * and why said before anybody confirms. The days and the reasons are the
 * server's; nothing about the period is worked out here.
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
        <AnonymizeDialog
          onDone={() => {
            setAsking(false);
            onAnonymized(t("anonymized"));
          }}
          onOpenChange={setAsking}
          order={order}
        />
      ) : null}
    </div>
  );
}

function AnonymizeDialog({
  onDone,
  onOpenChange,
  order,
}: {
  onDone: () => void;
  onOpenChange: (open: boolean) => void;
  order: Order;
}) {
  const t = useTranslations("Orders");
  const common = useTranslations("Common");
  const locale = useLocale();
  const [kept, setKept] = useState<CustomerKept[]>();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  useEffect(() => {
    let active = true;
    previewCustomerAnonymization(order.customer_id).then(
      (preview) => {
        if (active) setKept(preview.kept);
      },
      (error: unknown) => {
        if (active) setProblem(refusal(error, t("anonymizePreviewFailed")));
      },
    );
    return () => {
      active = false;
    };
  }, [order.customer_id, t]);

  async function confirm() {
    setBusy(true);
    setProblem(undefined);
    try {
      await anonymizeCustomer(order.customer_id);
      onDone();
    } catch (error) {
      setProblem(refusal(error, t("anonymizeFailed")));
    } finally {
      setBusy(false);
    }
  }

  // One reason for every order it holds for: said once, under the list.
  const reasons = [
    ...new Set(
      (kept ?? []).map((item) => (locale === "en" ? item.why.en : item.why.pl)),
    ),
  ].filter(Boolean);

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent closeLabel={common("close")}>
        <DialogHeader>
          <DialogTitle>
            {t("anonymizeTitle", { name: order.buyer_name })}
          </DialogTitle>
          <DialogDescription>{t("anonymizeGoes")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <p>{t("anonymizeStays")}</p>
          {kept === undefined && !problem ? (
            <p className="text-muted-foreground" role="status">
              {t("anonymizeChecking")}
            </p>
          ) : null}
          {kept?.length ? (
            <section aria-labelledby="anonymize-kept" className="space-y-1.5">
              <h3 className="font-medium" id="anonymize-kept">
                {t("anonymizeKeptTitle")}
              </h3>
              <ul className="list-disc space-y-1 pl-5">
                {kept.map((item) => (
                  <li key={`${item.kind}-${item.reference}`}>
                    {t("anonymizeKeptOrder", {
                      number: item.label,
                      until: formatDate(item.until, locale),
                    })}
                  </li>
                ))}
              </ul>
              {reasons.map((reason) => (
                <p className="text-muted-foreground" key={reason}>
                  {reason}
                </p>
              ))}
            </section>
          ) : null}
          {kept?.length === 0 ? <p>{t("anonymizeKeptNothing")}</p> : null}
        </div>
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
        <DialogFooter>
          <DialogClose render={<Button type="button" variant="outline" />}>
            {common("cancel")}
          </DialogClose>
          <Button
            disabled={busy || kept === undefined}
            onClick={() => void confirm()}
            type="button"
            variant="destructive"
          >
            {t("anonymizeConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
