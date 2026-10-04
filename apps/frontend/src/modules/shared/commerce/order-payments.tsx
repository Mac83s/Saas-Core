"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Undo2Icon } from "lucide-react";

import {
  ApiProblemError,
  readCommerceOptions,
  recordOrderPayment,
  voidOrderPayment,
  type CommerceOptions,
  type Order,
  type OrderPayment,
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
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { useDataTableLabels } from "#lib/data-table-labels";
import { formatDateTime } from "#lib/dates";
import { amountText, formatMoney, parseAmount } from "#lib/money";

type Method = CommerceOptions["manual_methods"][number];

/** What the server said, or the panel's own words when it said nothing. */
function refusal(error: unknown, fallback: string): string {
  if (!(error instanceof ApiProblemError)) return fallback;
  return error.problem.errors?.[0]?.message ?? fallback;
}

function isStale(error: unknown): boolean {
  return (
    error instanceof ApiProblemError &&
    error.problem.code === "order_version_conflict"
  );
}

/**
 * An order's payments (ADR-073 §4): what was paid and what is left — the
 * server's numbers, from the ledger — and each payment somebody marked. The
 * dialogs live here; the page opens „Oznacz wpłatę” from its header.
 */
export function OrderPayments({
  canManage,
  marking,
  onChanged,
  onMarkingChange,
  onStale,
  order,
}: {
  /** May mark and take back payments (`commerce.payments.manage`). */
  canManage: boolean;
  /** „Oznacz wpłatę” is open. */
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
  const [voiding, setVoiding] = useState<OrderPayment>();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const money = (minor: number) => formatMoney(minor, order.currency, locale);
  const canceled = order.status === "canceled";

  async function takeBack(payment: OrderPayment) {
    setBusy(true);
    setProblem(undefined);
    try {
      const next = await voidOrderPayment(order.id, payment.id, order.version);
      setVoiding(undefined);
      onChanged(next, t("voided", { amount: money(payment.amount_minor) }));
    } catch (error) {
      if (isStale(error)) {
        setVoiding(undefined);
        onStale(t("stale"));
      } else setProblem(refusal(error, t("saveFailed")));
    } finally {
      setBusy(false);
    }
  }

  const columns: ColumnDef<OrderPayment, unknown>[] = [
    {
      id: "when",
      header: t("colPaidAt"),
      enableSorting: false,
      meta: { primary: true },
      cell: ({ row: { original: payment } }) =>
        payment.paid_at ? (
          <time dateTime={payment.paid_at}>
            {formatDateTime(payment.paid_at, locale)}
          </time>
        ) : (
          "—"
        ),
    },
    {
      id: "method",
      header: t("colMethod"),
      enableSorting: false,
      cell: ({ row: { original: payment } }) => t(`methods.${payment.method}`),
    },
    {
      id: "amount",
      header: t("colAmount"),
      enableSorting: false,
      cell: ({ row: { original: payment } }) => (
        <span className="font-medium tabular-nums">
          {money(payment.amount_minor)}
        </span>
      ),
    },
    {
      id: "status",
      header: t("colPaymentStatus"),
      enableSorting: false,
      cell: ({ row: { original: payment } }) => (
        <Badge variant={payment.status === "succeeded" ? "success" : "neutral"}>
          {t(`paymentStatuses.${payment.status}`)}
        </Badge>
      ),
    },
    {
      id: "who",
      header: t("colRecordedBy"),
      enableSorting: false,
      cell: ({ row: { original: payment } }) => (
        <span className="wrap-anywhere">{payment.recorded_by || "—"}</span>
      ),
    },
    ...(canManage
      ? [
          {
            id: "actions",
            header: t("colActions"),
            meta: { actions: true },
            cell: ({ row: { original: payment } }) =>
              payment.status === "succeeded" &&
              (payment.method === "cash" || payment.method === "transfer") ? (
                <RowActions
                  items={[
                    {
                      label: t("void"),
                      onSelect: () => {
                        setProblem(undefined);
                        setVoiding(payment);
                      },
                      inline: true,
                      icon: <Undo2Icon aria-hidden="true" />,
                    },
                  ]}
                  label={t("paymentActionsFor", {
                    amount: money(payment.amount_minor),
                  })}
                />
              ) : null,
          } satisfies ColumnDef<OrderPayment, unknown>,
        ]
      : []),
  ];

  return (
    <section aria-labelledby="order-payments" className="space-y-3">
      <h2 className="font-medium" id="order-payments">
        {t("payments")}
      </h2>
      <dl className="max-w-sm space-y-1.5 text-sm">
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">
            {canceled && order.paid_minor > 0 ? t("paidToReturn") : t("paid")}
          </dt>
          <dd className="font-medium tabular-nums">
            {money(order.paid_minor)}
          </dd>
        </div>
        {canceled ? null : (
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">
              {order.due_minor < 0 ? t("overpaid") : t("due")}
            </dt>
            <dd className="font-medium tabular-nums">
              {money(Math.abs(order.due_minor))}
            </dd>
          </div>
        )}
      </dl>
      <DataTable
        caption={t("paymentsCaption")}
        columns={columns}
        data={order.payments}
        getRowId={(payment) => payment.id}
        labels={{ ...labels, empty: t("noPayments") }}
        pageSize={Number.MAX_SAFE_INTEGER}
      />
      {marking ? (
        <RecordPaymentDialog
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
                {t("voidTitle", { amount: money(voiding.amount_minor) })}
              </DialogTitle>
              <DialogDescription>{t("voidHint")}</DialogDescription>
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
                {t("voidConfirm")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}
    </section>
  );
}

/** „Oznacz wpłatę”: the amount starts at what is left to pay — the server's
 *  number — and the server refuses more than that. */
function RecordPaymentDialog({
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
  const [amount, setAmount] = useState(amountText(order.due_minor, locale));
  // What the company may mark by hand comes from the API.
  const [methods, setMethods] = useState<Method[]>([]);
  const [method, setMethod] = useState<Method>();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const money = (minor: number) => formatMoney(minor, order.currency, locale);

  useEffect(() => {
    let active = true;
    readCommerceOptions().then(
      (options) => {
        if (!active) return;
        setMethods(options.manual_methods);
        setMethod((current) => current ?? options.manual_methods[0]);
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
    const value = parseAmount(amount);
    if (value === null || value < 1) return setProblem(t("amountInvalid"));
    if (!method) return;
    setBusy(true);
    setProblem(undefined);
    try {
      const next = await recordOrderPayment(order.id, {
        amount_minor: value,
        method,
        expected_version: order.version,
      });
      onOpenChange(false);
      onChanged(next, t("recorded", { amount: money(value) }));
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
              {t("recordTitle", { number: order.number })}
            </DialogTitle>
            <DialogDescription>
              {t("recordHint", { due: money(order.due_minor) })}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="payment-amount">
                {`${t("amount")} (${order.currency})`}
              </FieldLabel>
              <Input
                id="payment-amount"
                inputMode="decimal"
                onChange={(event) => setAmount(event.target.value)}
                value={amount}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="payment-method">{t("method")}</FieldLabel>
              <NativeSelect
                disabled={!methods.length}
                id="payment-method"
                onChange={(event) => setMethod(event.target.value as Method)}
                value={method ?? ""}
              >
                {methods.map((value) => (
                  <option key={value} value={value}>
                    {t(`methods.${value}`)}
                  </option>
                ))}
              </NativeSelect>
            </Field>
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
            <Button disabled={busy || !method} type="submit">
              {t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
