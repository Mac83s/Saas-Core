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
            quote.prepayment.kind === "deposit"
              ? "prepayDeposit"
              : "prepayFull",
            {
              amount: money(quote.prepayment.amount_minor),
              days: quote.prepayment.transfer_due_days,
            },
          )}
        </p>
      ) : null}
    </section>
  );
}
