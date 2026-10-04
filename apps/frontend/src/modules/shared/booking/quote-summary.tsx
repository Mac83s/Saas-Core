"use client";

import { useLocale, useTranslations } from "next-intl";

import type { BookingPublicQuote } from "@saas-core/api-client";

/** A price as the customer reads it: the lines, what they pay, the deposit
 *  and how they pay (ADR-072 §7–§8). Every amount is the server's. */
export function QuoteSummary({
  quote,
  settled = false,
}: {
  quote: BookingPublicQuote;
  /** The booking no longer waits for its prepayment: the terms of paying it
   *  are not an instruction any more, so they are left out. */
  settled?: boolean;
}) {
  const t = useTranslations("BookingPrice");
  const locale = useLocale();
  const money = (minor: number) =>
    new Intl.NumberFormat(locale, {
      style: "currency",
      currency: quote.currency,
    }).format(minor / 100);
  return (
    <section
      aria-label={t("title")}
      className="space-y-2 rounded-lg border p-4 text-sm"
    >
      <p className="font-medium">{t("title")}</p>
      {quote.lines.length ? (
        <>
          <ul className="space-y-1">
            {quote.lines.map((line, index) => (
              <li className="flex justify-between gap-4" key={index}>
                <span>
                  {line.quantity > 1
                    ? t("times", { name: line.name, count: line.quantity })
                    : line.name}
                </span>
                <span className="tabular-nums">{money(line.gross_minor)}</span>
              </li>
            ))}
          </ul>
          <p className="flex justify-between gap-4 border-t pt-2 font-medium">
            <span>{t("total")}</span>
            <span className="tabular-nums">{money(quote.gross_minor)}</span>
          </p>
        </>
      ) : null}
      {quote.security_deposit_minor ? (
        <p className="text-muted-foreground">
          {t("deposit", { amount: money(quote.security_deposit_minor) })}
        </p>
      ) : null}
      {quote.payment_policy === "on_site" ? (
        <p className="text-muted-foreground">{t("payOnSite")}</p>
      ) : null}
      {/* What is paid before the booking is confirmed (ADR-073 §5). */}
      {quote.prepayment && !settled ? (
        <p className="font-medium">
          {t(
            quote.prepayment.kind !== "deposit"
              ? "prepayFull"
              : // The rest on site, or by a transfer said just below.
                quote.prepayment.balance_due_days_before != null
                ? "prepayDepositAhead"
                : "prepayDeposit",
            {
              amount: money(quote.prepayment.amount_minor),
              days: quote.prepayment.transfer_due_days,
            },
          )}
        </p>
      ) : null}
      {/* The rest by a transfer before the start — it stays due after the
          prepayment came. */}
      {quote.prepayment?.kind === "deposit" &&
      quote.prepayment.balance_due_days_before != null ? (
        <p>
          {t("balanceBefore", {
            amount: money(quote.gross_minor - quote.prepayment.amount_minor),
            days: quote.prepayment.balance_due_days_before,
          })}
        </p>
      ) : null}
      {quote.cancellation ? (
        <RefundThresholds cancellation={quote.cancellation} />
      ) : null}
    </section>
  );
}

/** What giving the booking up gives back, as the offer said when it was
 *  booked (ADR-072 §8): the thresholds, the longest notice first. */
export function RefundThresholds({
  cancellation,
}: {
  cancellation: NonNullable<BookingPublicQuote["cancellation"]>;
}) {
  const t = useTranslations("BookingPrice");
  const last = cancellation.refunds.at(-1);
  return (
    <div className="space-y-1 border-t pt-2">
      <p className="font-medium">{t("refundTitle")}</p>
      <ul className="space-y-0.5 text-muted-foreground">
        {cancellation.refunds.map((row) => (
          <li key={row.min_days_before}>
            {t("refundRow", {
              days: row.min_days_before,
              percent: row.refund_percent,
            })}
          </li>
        ))}
        {/* Less notice than the last threshold gives nothing back. */}
        {last && last.min_days_before > 0 && last.refund_percent > 0 ? (
          <li>{t("refundLater")}</li>
        ) : null}
      </ul>
      <p className="text-muted-foreground">
        {t(
          cancellation.applies_to === "deposit"
            ? "refundOfDeposit"
            : "refundOfPaid",
        )}
      </p>
    </div>
  );
}
