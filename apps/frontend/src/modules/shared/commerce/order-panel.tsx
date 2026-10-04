"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";

import {
  ApiProblemError,
  readOrder,
  type Order,
  type OrderLine,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import { DataTable, type ColumnDef } from "@saas-core/ui/components/data-table";

import { PanelPage } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import { formatDateTime } from "#lib/dates";
import { formatMoney } from "#lib/money";
import { isClosed, OrderPayments } from "./order-payments";
import { OrderRefunds } from "./order-refunds";
import { STATUS_TONE } from "./orders-panel";

type Failure = "notFound" | "orderLoadError";
type Consent = Order["consents"][number];

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap justify-between gap-x-4 gap-y-0.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right font-medium wrap-anywhere">
        {children}
      </dd>
    </div>
  );
}

/**
 * One order (ADR-073 §3–§4): who bought, the lines in force with what each
 * comes to, what was paid and where its booking is. Nothing is added up here
 * — the lines, the tax, the totals and what is left to pay are the server's.
 */
export function OrderPanel({
  canManagePayments = false,
  orderId,
}: {
  /** May mark and take back payments (`commerce.payments.manage`). */
  canManagePayments?: boolean;
  orderId: string;
}) {
  const t = useTranslations("Orders");
  const documents = useTranslations("CustomerDocuments");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const [order, setOrder] = useState<Order>();
  const [failure, setFailure] = useState<Failure>();
  const [attempt, setAttempt] = useState(0);
  const [marking, setMarking] = useState(false);
  const [refunding, setRefunding] = useState(false);
  const [notice, setNotice] = useState<string>();

  useEffect(() => {
    let active = true;
    readOrder(orderId).then(
      (next) => {
        if (active) setOrder(next);
      },
      (error: unknown) => {
        if (active)
          setFailure(
            error instanceof ApiProblemError && error.problem.status === 404
              ? "notFound"
              : "orderLoadError",
          );
      },
    );
    return () => {
      active = false;
    };
  }, [orderId, attempt]);

  const money = (minor: number) =>
    formatMoney(minor, order?.currency ?? "PLN", locale);
  const tax = (rate: OrderLine["tax_rate"]) =>
    rate === "zw"
      ? t("taxExempt")
      : rate === "np"
        ? t("taxOutside")
        : `${rate}%`;

  const columns: ColumnDef<OrderLine, unknown>[] = [
    {
      id: "line",
      header: t("colLine"),
      enableSorting: false,
      meta: { primary: true },
      cell: ({ row: { original: line } }) => {
        const target = line.target;
        const words = target
          ? {
              label: target.label,
              date: target.at ? formatDateTime(target.at, locale) : "",
            }
          : null;
        return (
          <span className="flex flex-col gap-0.5">
            <span className="font-medium wrap-anywhere">{line.name}</span>
            {target && words ? (
              target.href ? (
                <Link
                  className="text-sm text-primary hover:underline"
                  href={target.href}
                >
                  {t("inCalendar", words)}
                </Link>
              ) : (
                <span className="text-sm text-muted-foreground">
                  {t("target", words)}
                </span>
              )
            ) : null}
          </span>
        );
      },
    },
    {
      id: "quantity",
      header: t("colQuantity"),
      enableSorting: false,
      cell: ({ row: { original: line } }) => line.quantity,
    },
    {
      id: "unit",
      header: order?.amounts === "net" ? t("colUnitNet") : t("colUnitGross"),
      enableSorting: false,
      cell: ({ row: { original: line } }) => (
        <span className="tabular-nums">{money(line.unit_amount_minor)}</span>
      ),
    },
    {
      id: "tax",
      header: t("colTax"),
      enableSorting: false,
      cell: ({ row: { original: line } }) => tax(line.tax_rate),
    },
    {
      id: "net",
      header: t("colNet"),
      enableSorting: false,
      cell: ({ row: { original: line } }) => (
        <span className="tabular-nums">{money(line.net_minor)}</span>
      ),
    },
    {
      id: "vat",
      header: t("colVat"),
      enableSorting: false,
      cell: ({ row: { original: line } }) => (
        <span className="tabular-nums">{money(line.vat_minor)}</span>
      ),
    },
    {
      id: "gross",
      header: t("colGross"),
      enableSorting: false,
      cell: ({ row: { original: line } }) => (
        <span className="font-medium tabular-nums">
          {money(line.gross_minor)}
        </span>
      ),
    },
  ];

  const consent = (item: Consent) =>
    item.kind === "document" && item.document_kind
      ? t("consentDocument", {
          document: documents(`kinds.${item.document_kind}`),
          version: item.version ?? 0,
          language: item.locale.toUpperCase(),
        })
      : item.kind === "marketing"
        ? t("consentMarketing")
        : t("consentField");
  const consentColumns: ColumnDef<Consent, unknown>[] = [
    {
      id: "consent",
      header: t("colConsent"),
      enableSorting: false,
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <span className="wrap-anywhere">
          {consent(item)}
          {item.granted ? null : (
            <span className="text-muted-foreground">
              {` — ${t("consentWithdrawn")}`}
            </span>
          )}
        </span>
      ),
    },
    {
      id: "when",
      header: t("colConsentWhen"),
      enableSorting: false,
      cell: ({ row: { original: item } }) => (
        <time dateTime={item.created_at}>
          {formatDateTime(item.created_at, locale)}
        </time>
      ),
    },
  ];

  // What the order came to before its booking was priced again.
  const earlier = (order?.revisions ?? [])
    .filter((item) => item.revision < (order?.revision ?? 0))
    .map((item) => money(item.gross_minor));

  return (
    <PanelPage
      actions={
        order && canManagePayments && order.status !== "draft" ? (
          // A draft waits for the company's answer to the request first.
          <>
            {order.paid_minor > 0 ? (
              // What the terms owe the customer is the page's next step;
              // any other refund is the company's own idea.
              <Button
                onClick={() => setRefunding(true)}
                variant={
                  (order.refund_owed_minor ?? 0) > 0 ? "default" : "outline"
                }
              >
                {t("recordRefund")}
              </Button>
            ) : null}
            {!isClosed(order) && order.due_minor > 0 ? (
              <Button onClick={() => setMarking(true)}>
                {t("recordPayment")}
              </Button>
            ) : null}
          </>
        ) : undefined
      }
      eyebrow={t("title")}
      eyebrowHref="/panel/orders"
      notice={notice}
      subtitle={
        order ? (
          <Badge variant={STATUS_TONE[order.status]}>
            {t(`statuses.${order.status}`)}
          </Badge>
        ) : undefined
      }
      title={
        order?.number
          ? t("orderTitle", { number: order.number })
          : t("draftTitle")
      }
    >
      {failure ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{t(failure)}</p>
          {failure === "orderLoadError" ? (
            <Button
              onClick={() => {
                setFailure(undefined);
                setAttempt((value) => value + 1);
              }}
              variant="outline"
            >
              {t("retry")}
            </Button>
          ) : null}
        </div>
      ) : (
        <div className="space-y-6">
          {order ? (
            <div className="grid gap-4 md:grid-cols-2">
              <section
                aria-labelledby="order-about"
                className="space-y-2 rounded-lg border p-4 text-sm"
              >
                <h2 className="font-medium" id="order-about">
                  {t("about")}
                </h2>
                <dl className="space-y-1.5">
                  <Fact label={t("placed")}>
                    {order.placed_at ? (
                      <time dateTime={order.placed_at}>
                        {formatDateTime(order.placed_at, locale)}
                      </time>
                    ) : (
                      "—"
                    )}
                  </Fact>
                  <Fact label={t("source")}>
                    {t.has(`sources.${order.source}`)
                      ? t(`sources.${order.source}`)
                      : order.source}
                  </Fact>
                  <Fact label={t("channel")}>
                    {t(`channels.${order.channel}`)}
                  </Fact>
                </dl>
              </section>
              <section
                aria-labelledby="order-buyer"
                className="space-y-2 rounded-lg border p-4 text-sm"
              >
                <h2 className="font-medium" id="order-buyer">
                  {t("buyer")}
                </h2>
                <dl className="space-y-1.5">
                  <Fact label={t("name")}>{order.buyer_name}</Fact>
                  <Fact label={t("email")}>
                    {order.buyer_email ? (
                      <a
                        className="text-primary hover:underline"
                        href={`mailto:${order.buyer_email}`}
                      >
                        {order.buyer_email}
                      </a>
                    ) : (
                      <span className="font-normal text-muted-foreground">
                        {t("notGiven")}
                      </span>
                    )}
                  </Fact>
                  <Fact label={t("phone")}>
                    {order.buyer_phone ? (
                      <a
                        className="text-primary hover:underline"
                        href={`tel:${order.buyer_phone.replaceAll(" ", "")}`}
                      >
                        {order.buyer_phone}
                      </a>
                    ) : (
                      <span className="font-normal text-muted-foreground">
                        {t("notGiven")}
                      </span>
                    )}
                  </Fact>
                </dl>
              </section>
            </div>
          ) : null}
          {order ? (
            <OrderPayments
              canManage={canManagePayments}
              marking={marking}
              onChanged={(next, text) => {
                setOrder(next);
                setNotice(text);
              }}
              onMarkingChange={setMarking}
              onStale={(text) => {
                setNotice(text);
                setAttempt((value) => value + 1);
              }}
              order={order}
            />
          ) : null}
          {order ? (
            <OrderRefunds
              canManage={canManagePayments}
              marking={refunding}
              onChanged={(next, text) => {
                setOrder(next);
                setNotice(text);
              }}
              onMarkingChange={setRefunding}
              onStale={(text) => {
                setNotice(text);
                setAttempt((value) => value + 1);
              }}
              order={order}
            />
          ) : null}
          <section aria-labelledby="order-lines" className="space-y-3">
            <h2 className="font-medium" id="order-lines">
              {t("lines")}
            </h2>
            <DataTable
              caption={t("linesCaption")}
              columns={columns}
              data={order?.lines ?? []}
              getRowId={(line) => String(line.position)}
              labels={labels}
              loading={!order}
              pageSize={Number.MAX_SAFE_INTEGER}
            />
            {order ? (
              <dl className="ml-auto max-w-sm space-y-1.5 text-sm">
                <Fact label={t("totalNet")}>
                  <span className="tabular-nums">{money(order.net_minor)}</span>
                </Fact>
                <Fact label={t("totalVat")}>
                  <span className="tabular-nums">{money(order.vat_minor)}</span>
                </Fact>
                <Fact label={t("totalGross")}>
                  <span className="text-base tabular-nums">
                    {money(order.gross_minor)}
                  </span>
                </Fact>
              </dl>
            ) : null}
            {earlier.length ? (
              <p className="text-sm text-muted-foreground">
                {t("repriced", { amounts: earlier.join(", ") })}
              </p>
            ) : null}
          </section>
          {order ? (
            <section aria-labelledby="order-consents" className="space-y-3">
              <h2 className="font-medium" id="order-consents">
                {t("consents")}
              </h2>
              <DataTable
                caption={t("consentsCaption")}
                columns={consentColumns}
                data={order.consents}
                getRowId={(item) =>
                  `${item.created_at}-${item.kind}-${item.document_kind ?? ""}`
                }
                labels={{ ...labels, empty: t("noConsents") }}
                pageSize={Number.MAX_SAFE_INTEGER}
              />
            </section>
          ) : null}
        </div>
      )}
    </PanelPage>
  );
}
