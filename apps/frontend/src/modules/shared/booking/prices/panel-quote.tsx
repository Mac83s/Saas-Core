"use client";

import { useLocale, useTranslations } from "next-intl";

import {
  ApiProblemError,
  type BookingQuote,
  type BookingQuoteLine,
} from "@saas-core/api-client";

import { RefundThresholds } from "../quote-summary";
import { formatMoney } from "./money";

/**
 * A booking's price as the company reads it (ADR-072 §7): the lines, net, tax
 * and what the customer pays, the deposit beside the total and how they pay.
 * Every amount is the server's; nothing is added up here.
 */
export function PanelQuote({
  changed = false,
  quote,
  source,
  title,
}: {
  /** The price is another one than the form showed (409 `quote_changed`). */
  changed?: boolean;
  quote: BookingQuote;
  /** The price a line came from, in words — the price list's preview says it. */
  source?: (line: BookingQuoteLine) => string | undefined;
  title?: string;
}) {
  const t = useTranslations("PriceList");
  // The customer's own words for the rest due by a transfer.
  const price = useTranslations("BookingPrice");
  const locale = useLocale();
  const money = (minor: number) => formatMoney(minor, quote.currency, locale);
  const heading = title ?? t("quoteTitle");
  return (
    <section
      aria-label={heading}
      className="space-y-2 rounded-lg border p-4 text-sm"
    >
      <p className="font-medium">{heading}</p>
      {changed ? (
        <p className="font-medium text-warning-foreground" role="alert">
          {t("quoteChanged")}
        </p>
      ) : null}
      {quote.lines.length ? (
        <>
          <ul className="space-y-1">
            {quote.lines.map((line, index) => {
              const from = source?.(line);
              return (
                <li className="flex justify-between gap-4" key={index}>
                  <span className="min-w-0 wrap-anywhere">
                    {line.quantity > 1
                      ? t(
                          quote.amounts === "net"
                            ? "quoteTimesNet"
                            : "quoteTimes",
                          {
                            name: line.name,
                            count: line.quantity,
                            amount: money(line.unit_amount_minor),
                          },
                        )
                      : line.name}
                    {from ? (
                      <span className="block text-muted-foreground">
                        {from}
                      </span>
                    ) : null}
                  </span>
                  <span className="shrink-0 tabular-nums">
                    {money(line.gross_minor)}
                  </span>
                </li>
              );
            })}
          </ul>
          <dl className="space-y-1 border-t pt-2">
            <div className="flex justify-between gap-4 text-muted-foreground">
              <dt>{t("quoteNet")}</dt>
              <dd className="tabular-nums">{money(quote.net_minor)}</dd>
            </div>
            <div className="flex justify-between gap-4 text-muted-foreground">
              <dt>{t("quoteVat")}</dt>
              <dd className="tabular-nums">{money(quote.vat_minor)}</dd>
            </div>
            <div className="flex justify-between gap-4 font-medium">
              <dt>{t("quoteGross")}</dt>
              <dd className="tabular-nums">{money(quote.gross_minor)}</dd>
            </div>
          </dl>
        </>
      ) : null}
      {quote.security_deposit_minor ? (
        <p className="text-muted-foreground">
          {t("quoteDeposit", { amount: money(quote.security_deposit_minor) })}
        </p>
      ) : null}
      {quote.payment_policy === "on_site" ? (
        <p className="text-muted-foreground">{t("payOnSite")}</p>
      ) : null}
      {/* What the booking waits for before it is confirmed (ADR-073 §5). */}
      {quote.prepayment ? (
        <p className="text-muted-foreground">
          {t(
            quote.prepayment.kind !== "deposit"
              ? "prepayFull"
              : quote.prepayment.balance_due_days_before != null
                ? "prepayDepositAhead"
                : "prepayDeposit",
            {
              amount: money(quote.prepayment.amount_minor),
              days: quote.prepayment.transfer_due_days,
            },
          )}
        </p>
      ) : null}
      {quote.prepayment?.kind === "deposit" &&
      quote.prepayment.balance_due_days_before != null ? (
        <p className="text-muted-foreground">
          {price("balanceBefore", {
            amount: money(quote.gross_minor - quote.prepayment.amount_minor),
            days: quote.prepayment.balance_due_days_before,
          })}
        </p>
      ) : null}
      {/* The terms the booking is given up under, as the customer reads them. */}
      {quote.cancellation ? (
        <RefundThresholds cancellation={quote.cancellation} />
      ) : null}
    </section>
  );
}

/** Whether the offer has a price at all; without one a booking shows none. */
export const isPriced = (quote: BookingQuote | null | undefined) =>
  Boolean(quote && (quote.lines.length || quote.security_deposit_minor));

/** The new price a booking was refused with (409 `quote_changed`, ADR-072 §7). */
export function changedQuote(error: unknown): BookingQuote | undefined {
  if (!(error instanceof ApiProblemError)) return undefined;
  if (error.problem.code !== "quote_changed") return undefined;
  return (error.problem.detail as { quote?: BookingQuote } | null)?.quote;
}
