"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Undo2Icon } from "lucide-react";

import {
  readCommerceOptions,
  recordOrderRefund,
  voidOrderRefund,
  type CommerceOptions,
  type Order,
  type OrderRefund,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import {
  Field,
  FieldDescription,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Textarea } from "@saas-core/ui/components/textarea";

import { useDataTableLabels } from "#lib/data-table-labels";
import { formatDateTime } from "#lib/dates";
import { amountText, formatMoney, parseAmount } from "#lib/money";

import { isStale, refusal } from "./order-payments";

type Method = CommerceOptions["manual_methods"][number];
/** As the API bounds the company's reason for a refund. */
const REASON_MAX_LENGTH = 300;

/** Whether the order has anything to give back or a refund to show. */
export function hasRefunds(order: Order): boolean {
  return (order.refunds?.length ?? 0) > 0 || (order.refund_owed_minor ?? 0) > 0;
}

/**
 * What the company gave back for an order (ADR-073 §8): the refunds it
 * marked, and what the order's terms still owe the customer — the server's
 * number, settled when the booking was called off. The company returns the
 * money itself; here it only says that it did.
 */
export function OrderRefunds({
  canManage,
  marking,
  onChanged,
  onMarkingChange,
  onStale,
  order,
}: {
  /** May mark and take back refunds (`commerce.payments.manage`). */
  canManage: boolean;
  /** „Oznacz zwrot” is open. */
  marking: boolean;
  onChanged: (order: Order, notice: string) => void;
  onMarkingChange: (open: boolean) => void;
  /** Somebody else changed the order: the page reads it again. */
  onStale: (notice: string) => void;
  order: Order;
}) {
  const t = useTranslations("Orders");
  const common = useTranslations("Common");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const [voiding, setVoiding] = useState<OrderRefund>();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const money = (minor: number) => formatMoney(minor, order.currency, locale);
  const refunds = order.refunds ?? [];
  const owed = order.refund_owed_minor ?? 0;

  async function takeBack(refund: OrderRefund) {
    setBusy(true);
    setProblem(undefined);
    try {
      const next = await voidOrderRefund(order.id, refund.id, order.version);
      setVoiding(undefined);
      onChanged(
        next,
        t("refundVoided", { amount: money(refund.amount_minor) }),
      );
    } catch (error) {
      if (isStale(error)) {
        setVoiding(undefined);
        onStale(t("stale"));
      } else setProblem(refusal(error, t("saveFailed")));
    } finally {
      setBusy(false);
    }
  }

  const columns: ColumnDef<OrderRefund, unknown>[] = [
    {
      id: "when",
      header: t("colRefundedAt"),
      enableSorting: false,
      meta: { primary: true },
      cell: ({ row: { original: refund } }) => (
        <time dateTime={refund.refunded_at}>
          {formatDateTime(refund.refunded_at, locale)}
        </time>
      ),
    },
    {
      id: "method",
      header: t("colRefundMethod"),
      enableSorting: false,
      cell: ({ row: { original: refund } }) =>
        t(`refundMethods.${refund.method}`),
    },
    {
      id: "amount",
      header: t("colAmount"),
      enableSorting: false,
      cell: ({ row: { original: refund } }) => (
        <span className="font-medium tabular-nums">
          {money(refund.amount_minor)}
        </span>
      ),
    },
    {
      id: "status",
      header: t("colPaymentStatus"),
      enableSorting: false,
      cell: ({ row: { original: refund } }) => (
        <Badge variant={refund.status === "succeeded" ? "success" : "neutral"}>
          {t(`refundStatuses.${refund.status}`)}
        </Badge>
      ),
    },
    {
      id: "reason",
      header: t("colRefundReason"),
      enableSorting: false,
      cell: ({ row: { original: refund } }) => (
        <span className="wrap-anywhere">{refund.reason || "—"}</span>
      ),
    },
    {
      id: "who",
      header: t("colRecordedBy"),
      enableSorting: false,
      cell: ({ row: { original: refund } }) => (
        <span className="wrap-anywhere">{refund.recorded_by || "—"}</span>
      ),
    },
    ...(canManage
      ? [
          {
            id: "actions",
            header: t("colActions"),
            meta: { actions: true },
            cell: ({ row: { original: refund } }) =>
              refund.status === "succeeded" ? (
                <RowActions
                  items={[
                    {
                      label: t("void"),
                      onSelect: () => {
                        setProblem(undefined);
                        setVoiding(refund);
                      },
                      inline: true,
                      icon: <Undo2Icon aria-hidden="true" />,
                    },
                  ]}
                  label={t("refundActionsFor", {
                    amount: money(refund.amount_minor),
                  })}
                />
              ) : null,
          } satisfies ColumnDef<OrderRefund, unknown>,
        ]
      : []),
  ];

  return (
    <>
      {hasRefunds(order) ? (
        <section aria-labelledby="order-refunds" className="space-y-3">
          <h2 className="font-medium" id="order-refunds">
            {t("refunds")}
          </h2>
          {owed > 0 ? (
            <p className="max-w-prose text-sm" role="note">
              {t("refundOwedHint", { amount: money(owed) })}
            </p>
          ) : null}
          <DataTable
            caption={t("refundsCaption")}
            columns={columns}
            data={refunds}
            getRowId={(refund) => refund.id}
            labels={{ ...labels, empty: t("noRefunds") }}
            pageSize={Number.MAX_SAFE_INTEGER}
          />
        </section>
      ) : null}
      {marking ? (
        <RecordRefundDialog
          onChanged={onChanged}
          onOpenChange={onMarkingChange}
          onStale={onStale}
          order={order}
        />
      ) : null}
      {voiding ? (
        <Dialog
          onOpenChange={(open) => {
            if (!open) setVoiding(undefined);
          }}
          open
        >
          <DialogContent closeLabel={common("close")}>
            <DialogHeader>
              <DialogTitle>
                {t("refundVoidTitle", { amount: money(voiding.amount_minor) })}
              </DialogTitle>
              <DialogDescription>
                {t("refundVoidHint")}{" "}
                {order.buyer_email ? t("refundVoidMail") : t("refundNoMail")}
              </DialogDescription>
            </DialogHeader>
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
                disabled={busy}
                onClick={() => void takeBack(voiding)}
                type="button"
                variant="destructive"
              >
                {t("refundVoidConfirm")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}
    </>
  );
}

/** „Oznacz zwrot”: the amount starts at what the order's terms still owe the
 *  customer, else at what they paid. More than the terms give back needs the
 *  company's reason; the server refuses more than was paid. */
function RecordRefundDialog({
  onChanged,
  onOpenChange,
  onStale,
  order,
}: {
  onChanged: (order: Order, notice: string) => void;
  onOpenChange: (open: boolean) => void;
  onStale: (notice: string) => void;
  order: Order;
}) {
  const t = useTranslations("Orders");
  const common = useTranslations("Common");
  const locale = useLocale();
  const owed = order.refund_owed_minor ?? 0;
  const [amount, setAmount] = useState(
    amountText(owed > 0 ? owed : order.paid_minor, locale),
  );
  const [methods, setMethods] = useState<Method[]>([]);
  const [method, setMethod] = useState<Method>();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const money = (minor: number) => formatMoney(minor, order.currency, locale);
  const value = parseAmount(amount);
  // Beyond what the terms give back the company says why.
  const beyond = value !== null && value > owed;

  useEffect(() => {
    let active = true;
    readCommerceOptions().then(
      (options) => {
        if (!active) return;
        setMethods(options.manual_methods);
        // Money that came by a transfer usually goes back the same way.
        setMethod(
          (current) =>
            current ??
            options.manual_methods.find((item) => item === "transfer") ??
            options.manual_methods[0],
        );
      },
      () => {
        if (active) setProblem(t("saveFailed"));
      },
    );
    return () => {
      active = false;
    };
  }, [t]);

  async function save() {
    if (value === null || value < 1) return setProblem(t("amountInvalid"));
    if (beyond && !reason.trim()) return setProblem(t("refundReasonRequired"));
    if (!method) return;
    setBusy(true);
    setProblem(undefined);
    try {
      const next = await recordOrderRefund(order.id, {
        amount_minor: value,
        method,
        reason: reason.trim(),
        expected_version: order.version,
      });
      onOpenChange(false);
      onChanged(next, t("refundRecorded", { amount: money(value) }));
    } catch (error) {
      if (isStale(error)) {
        onOpenChange(false);
        onStale(t("stale"));
      } else setProblem(refusal(error, t("saveFailed")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent closeLabel={common("close")}>
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <DialogHeader>
            <DialogTitle>
              {t("refundTitle", { number: order.number })}
            </DialogTitle>
            <DialogDescription>
              {owed > 0
                ? t("refundHintOwed", {
                    owed: money(owed),
                    paid: money(order.paid_minor),
                  })
                : t("refundHint", { paid: money(order.paid_minor) })}{" "}
              {order.buyer_email ? t("refundMail") : t("refundNoMail")}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="refund-amount">
                {`${t("amount")} (${order.currency})`}
              </FieldLabel>
              <Input
                id="refund-amount"
                inputMode="decimal"
                onChange={(event) => setAmount(event.target.value)}
                value={amount}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="refund-method">
                {t("refundMethod")}
              </FieldLabel>
              <NativeSelect
                disabled={!methods.length}
                id="refund-method"
                onChange={(event) => setMethod(event.target.value as Method)}
                value={method ?? ""}
              >
                {methods.map((item) => (
                  <option key={item} value={item}>
                    {t(`refundMethods.${item}`)}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          </div>
          <Field>
            <FieldLabel htmlFor="refund-reason">
              {beyond ? t("refundReason") : t("refundReasonOptional")}
            </FieldLabel>
            <Textarea
              aria-describedby="refund-reason-hint"
              id="refund-reason"
              maxLength={REASON_MAX_LENGTH}
              onChange={(event) => setReason(event.target.value)}
              rows={2}
              value={reason}
            />
            <FieldDescription id="refund-reason-hint">
              {t("refundReasonHint")}
            </FieldDescription>
          </Field>
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button disabled={busy || !method} type="submit">
              {t("refundSave")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
