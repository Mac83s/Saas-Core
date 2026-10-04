"use client";

import { useLocale, useTranslations } from "next-intl";

import type { BookingPublicAppointment } from "@saas-core/api-client";

type Awaited = NonNullable<BookingPublicAppointment["payment"]>;

/**
 * What a customer is to transfer (ADR-073 §5) — before their booking is
 * confirmed, or the rest of a confirmed one's price: the amount, the date,
 * the company's account and the order's number as the transfer's title.
 * Every value is the server's.
 */
export function TransferDetails({
  payment,
  zone,
}: {
  payment: Awaited;
  zone: string;
}) {
  const t = useTranslations("BookingPrice");
  const locale = useLocale();
  const amount = new Intl.NumberFormat(locale, {
    style: "currency",
    currency: payment.currency,
  }).format(payment.amount_minor / 100);
  const due = new Intl.DateTimeFormat(locale, {
    dateStyle: "full",
    timeStyle: "short",
    timeZone: zone,
  }).format(new Date(payment.due_at));
  return (
    <section
      aria-label={t("transferTitle")}
      className="space-y-3 rounded-lg border border-warning-foreground/40 p-4 text-sm"
    >
      <p className="font-medium">{t("transferTitle")}</p>
      <p>
        {t(
          payment.kind !== "balance"
            ? "transferHint"
            : // A late balance calls nothing off; the date still stands.
              new Date(payment.due_at) < new Date()
              ? "balanceOverdueHint"
              : "balanceHint",
          { amount, due },
        )}
      </p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5">
        <dt className="text-muted-foreground">{t("transferAmount")}</dt>
        <dd className="font-medium tabular-nums">{amount}</dd>
        <dt className="text-muted-foreground">{t("transferHolder")}</dt>
        <dd className="font-medium">{payment.account_holder}</dd>
        <dt className="text-muted-foreground">{t("transferAccount")}</dt>
        <dd className="font-medium break-all tabular-nums">
          {payment.account_number}
        </dd>
        {payment.bank_name ? (
          <>
            <dt className="text-muted-foreground">{t("transferBank")}</dt>
            <dd className="font-medium">{payment.bank_name}</dd>
          </>
        ) : null}
        <dt className="text-muted-foreground">{t("transferReference")}</dt>
        <dd className="font-medium">{payment.number}</dd>
      </dl>
    </section>
  );
}
