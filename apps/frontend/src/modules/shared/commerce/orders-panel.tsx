"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { EyeIcon } from "lucide-react";

import {
  ApiProblemError,
  listOrders,
  readCommerceOptions,
  type CommerceOptions,
  type OrderPage,
  type OrderSummary,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  DataTableFilter,
  DataTableSearch,
  RowActions,
  type ColumnDef,
  type DataTableQuery,
} from "@saas-core/ui/components/data-table";

import { PanelPage } from "#components/panel/panel-page";
import { PlanGate } from "#components/panel/plan-gate";
import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import { formatDateTime } from "#lib/dates";
import { formatMoney } from "./money";

const PAGE_SIZE = 25;
type Failure = "loadError" | "permission" | "plan";
type Status = OrderSummary["status"];

/** What needs doing is amber, what is settled is green, the rest asks
 *  nothing (UX-018). */
export const STATUS_TONE: Record<
  Status,
  "warning" | "success" | "info" | "neutral"
> = {
  draft: "neutral",
  awaiting_payment: "warning",
  partially_paid: "warning",
  paid: "success",
  fulfilled: "info",
  completed: "success",
  canceled: "neutral",
  refunded: "neutral",
};

function failureKey(error: unknown): Failure {
  if (error instanceof ApiProblemError) {
    if (error.problem.code === "entitlement_required") return "plan";
    if (error.problem.status === 403) return "permission";
  }
  return "loadError";
}

/**
 * Zamówienia (ADR-073 §3): what the company's customers bought, newest first.
 * The server pages, filters and searches the list; every amount is the
 * server's.
 */
export function OrdersPanel({
  canManageBilling = false,
}: {
  /** Whoever may change the plan gets the way to the plans. */
  canManageBilling?: boolean;
}) {
  const t = useTranslations("Orders");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const [query, setQuery] = useState<DataTableQuery>({
    pageIndex: 0,
    pageSize: PAGE_SIZE,
    sorting: [],
    search: "",
  });
  const [search, setSearch] = useState("");
  // What the API was asked for: typing asks once per pause, not once per key.
  const [term, setTerm] = useState("");
  const [status, setStatus] = useState<Status | "">("");
  const [channel, setChannel] = useState<OrderSummary["channel"] | "">("");
  const [options, setOptions] = useState<CommerceOptions>();
  const [page, setPage] = useState<OrderPage>();
  const [failure, setFailure] = useState<Failure>();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    // The filters' choices; the list itself says when reading is refused.
    readCommerceOptions().then(
      (next) => {
        if (active) setOptions(next);
      },
      () => undefined,
    );
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      setTerm(search.trim());
      setQuery((current) => ({ ...current, pageIndex: 0 }));
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const load = useCallback(async () => {
    setLoading(true);
    setFailure(undefined);
    try {
      setPage(
        await listOrders({
          page: query.pageIndex + 1,
          pageSize: query.pageSize,
          status,
          channel,
          q: term,
        }),
      );
    } catch (error) {
      setFailure(failureKey(error));
    } finally {
      setLoading(false);
    }
  }, [query.pageIndex, query.pageSize, status, channel, term]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load on query change
    void load();
  }, [load]);

  /** A new search or filter starts from the first page. */
  const firstPage = () => setQuery((current) => ({ ...current, pageIndex: 0 }));
  const narrowed = Boolean(term || status || channel);
  const clear = () => {
    setSearch("");
    setTerm("");
    setStatus("");
    setChannel("");
    firstPage();
  };
  const numberOf = (order: OrderSummary) => order.number || t("noNumber");

  const columns: ColumnDef<OrderSummary, unknown>[] = [
    {
      id: "number",
      header: t("colNumber"),
      enableSorting: false,
      meta: { primary: true },
      cell: ({ row: { original: order } }) => (
        <Link
          className="font-medium hover:underline"
          href={`/panel/orders/${order.id}`}
        >
          {numberOf(order)}
        </Link>
      ),
    },
    {
      id: "placed",
      header: t("colPlaced"),
      enableSorting: false,
      cell: ({ row: { original: order } }) =>
        order.placed_at ? (
          <time dateTime={order.placed_at}>
            {formatDateTime(order.placed_at, locale)}
          </time>
        ) : (
          "—"
        ),
    },
    {
      id: "buyer",
      header: t("colBuyer"),
      enableSorting: false,
      cell: ({ row: { original: order } }) => (
        <span className="wrap-anywhere">{order.buyer_name}</span>
      ),
    },
    {
      id: "total",
      header: t("colTotal"),
      enableSorting: false,
      cell: ({ row: { original: order } }) => (
        <span className="tabular-nums">
          {formatMoney(order.gross_minor, order.currency, locale)}
        </span>
      ),
    },
    {
      id: "status",
      header: t("colStatus"),
      enableSorting: false,
      cell: ({ row: { original: order } }) => (
        <Badge variant={STATUS_TONE[order.status]}>
          {t(`statuses.${order.status}`)}
        </Badge>
      ),
    },
    {
      id: "channel",
      header: t("colChannel"),
      enableSorting: false,
      cell: ({ row: { original: order } }) => t(`channels.${order.channel}`),
    },
    {
      id: "actions",
      header: t("colActions"),
      meta: { actions: true },
      cell: ({ row: { original: order } }) => (
        <RowActions
          items={[
            {
              label: t("open"),
              link: <Link href={`/panel/orders/${order.id}`} />,
              inline: true,
              main: true,
              icon: <EyeIcon aria-hidden="true" />,
            },
          ]}
          label={t("actionsFor", { number: numberOf(order) })}
        />
      ),
    },
  ];

  return (
    <PanelPage description={t("description")} title={t("title")}>
      {failure === "plan" ? (
        <PlanGate
          action={
            canManageBilling
              ? { href: "/panel/settings/billing", label: t("planAction") }
              : undefined
          }
          title={t("planTitle")}
        >
          {canManageBilling ? t("plan") : t("planOwner")}
        </PlanGate>
      ) : failure ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{t(failure)}</p>
          {failure === "loadError" ? (
            <Button onClick={() => void load()} variant="outline">
              {t("retry")}
            </Button>
          ) : null}
        </div>
      ) : (
        <DataTable
          activeFilters={[status, channel].filter(Boolean).length}
          caption={t("caption")}
          columns={columns}
          data={page?.items ?? []}
          emptyAction={
            narrowed ? (
              <Button onClick={clear} variant="outline">
                {t("clearFilters")}
              </Button>
            ) : undefined
          }
          filters={
            <>
              <DataTableFilter
                id="orders-status"
                label={t("filterStatus")}
                onChange={(event) => {
                  setStatus(event.target.value as Status | "");
                  firstPage();
                }}
                value={status}
              >
                <option value="">{t("all")}</option>
                {(options?.statuses ?? []).map((value) => (
                  <option key={value} value={value}>
                    {t(`statuses.${value}`)}
                  </option>
                ))}
              </DataTableFilter>
              <DataTableFilter
                id="orders-channel"
                label={t("filterChannel")}
                onChange={(event) => {
                  setChannel(
                    event.target.value as OrderSummary["channel"] | "",
                  );
                  firstPage();
                }}
                value={channel}
              >
                <option value="">{t("all")}</option>
                {(options?.channels ?? []).map((value) => (
                  <option key={value} value={value}>
                    {t(`channels.${value}`)}
                  </option>
                ))}
              </DataTableFilter>
            </>
          }
          getRowId={(order) => order.id}
          labels={{
            ...labels,
            empty: narrowed ? t("emptyFiltered") : t("empty"),
          }}
          loading={loading}
          onQueryChange={setQuery}
          pageSize={PAGE_SIZE}
          query={query}
          rowCount={page?.total ?? 0}
          toolbar={
            <DataTableSearch
              hint={t("searchHint")}
              id="orders-search"
              label={t("search")}
              onChange={setSearch}
              placeholder={t("searchPlaceholder")}
              value={search}
            />
          }
        />
      )}
    </PanelPage>
  );
}
