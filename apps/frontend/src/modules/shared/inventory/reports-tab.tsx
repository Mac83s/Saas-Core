"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import {
  getInventoryStockValue,
  getInventoryUsage,
  type InventoryStockValueGroup,
  type InventoryStockValueReport,
  type InventoryUsageGroup,
  type InventoryUsageReport,
} from "@saas-core/api-client";
import {
  DataTable,
  DataTableFilter,
  type ColumnDef,
  type DataTableQuery,
} from "@saas-core/ui/components/data-table";

import { PanelPage } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";
import { formatDateRange, formatDateTime } from "#lib/dates";
import {
  PERIODS,
  periodDays,
  type PeriodKey,
} from "../booking/people/person-facts";
import {
  type InventoryData,
  loadProblem,
  type LoadProblem,
  LoadProblemNotice,
  locationLabel,
  type PageFrame,
  useFormat,
} from "./shared";

const STOCK = ["item", "category", "location"] as const;
const USAGE = ["item", "person", "service", "customer", "visit"] as const;
/** „stock:item”, „usage:visit”: which report and what a row of it is. */
type Report =
  `stock:${InventoryStockValueGroup}` | `usage:${InventoryUsageGroup}`;
type StockRow = InventoryStockValueReport["rows"][number];
type UsageRow = InventoryUsageReport["rows"][number];
const PAGE = 50;

/**
 * Magazyn › Raporty (phase 10b): what the stock is worth now and what went out
 * in a period — by item, person, service, customer, or visit by visit (the
 * cost of a visit). For whoever runs the warehouse: the numbers are what the
 * company paid (answer 43a), and the API refuses anybody else.
 */
export function ReportsTab({
  data,
  page,
  zone,
}: {
  data: InventoryData;
  page: PageFrame;
  zone: string;
}) {
  const t = useTranslations("Inventory");
  const periods = useTranslations("StaffFacts");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const { amount, money } = useFormat();
  const [now] = useState(() => new Date());
  const [report, setReport] = useState<Report>("stock:item");
  const [period, setPeriod] = useState<PeriodKey>("month");
  const [locationId, setLocationId] = useState("");
  const [query, setQuery] = useState<DataTableQuery>({
    pageIndex: 0,
    pageSize: PAGE,
    sorting: [],
    search: "",
  });
  // Each answer remembers what it answers: a report of another choice is
  // „loading”, never the previous one's rows under the new heading.
  const [answer, setAnswer] = useState<{
    asked: string;
    stock?: InventoryStockValueReport;
    usage?: InventoryUsageReport;
  }>();
  const [failed, setFailed] = useState<LoadProblem>();
  const [kind, group] = report.split(":") as ["stock" | "usage", string];
  const { from, to } = periodDays(period, now, zone);
  const asked =
    kind === "stock"
      ? `${report}:${locationId}`
      : `${report}:${from}:${to}:${query.pageIndex}`;
  const stock = answer?.asked === asked ? answer.stock : undefined;
  const usage = answer?.asked === asked ? answer.usage : undefined;

  useEffect(() => {
    let current = true;
    const failure = (error: unknown) => {
      if (current) setFailed(loadProblem(error));
    };
    if (kind === "stock") {
      getInventoryStockValue({
        group: group as InventoryStockValueGroup,
        locationId: locationId || undefined,
      }).then((next) => {
        if (!current) return;
        setAnswer({ asked, stock: next });
        setFailed(undefined);
      }, failure);
    } else {
      getInventoryUsage({
        group: group as InventoryUsageGroup,
        from,
        to,
        page: query.pageIndex + 1,
        pageSize: PAGE,
      }).then((next) => {
        if (!current) return;
        setAnswer({ asked, usage: next });
        setFailed(undefined);
      }, failure);
    }
    return () => {
      current = false;
    };
  }, [asked, kind, group, locationId, from, to, query.pageIndex]);

  const choose = (next: Report) => {
    setReport(next);
    setQuery((current) => ({ ...current, pageIndex: 0 }));
  };

  // A row without a key is what belongs to nothing: no category, no visit.
  const named = (row: { key: string; name: string }) => {
    if (row.name) return row.name;
    if (row.key === "hidden") return t("reportHiddenCustomer");
    if (group === "category") return t("reportNoCategory");
    return t("reportNoVisit");
  };

  const stockColumns: ColumnDef<StockRow, unknown>[] = [
    {
      id: "name",
      accessorFn: named,
      header: t(`reportRow_${group}`),
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <p className="font-medium wrap-anywhere">
          {group === "location"
            ? (placeName(row.key) ?? named(row))
            : named(row)}
        </p>
      ),
    },
    ...(group === "item"
      ? ([
          {
            id: "quantity",
            accessorFn: (row) => Number(row.quantity ?? 0),
            header: t("quantity"),
            meta: { numeric: true },
            cell: ({ row: { original: row } }) =>
              `${amount(row.quantity ?? 0)} ${row.unit ? t(`unit_${row.unit}`) : ""}`,
          },
          {
            id: "cost",
            accessorFn: (row) => row.average_cost_minor ?? 0,
            header: t("averageCost"),
            meta: { numeric: true },
            cell: ({ row: { original: row } }) =>
              money(row.average_cost_minor, row.currency),
          },
        ] satisfies ColumnDef<StockRow, unknown>[])
      : []),
    {
      id: "value",
      accessorKey: "value_minor",
      header: t("reportValue"),
      meta: { numeric: true },
      cell: ({ row: { original: row } }) =>
        money(row.value_minor, row.currency),
    },
  ];

  const usageColumns: ColumnDef<UsageRow, unknown>[] = [
    {
      id: "name",
      header: t(`reportRow_${group}`),
      enableSorting: false,
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <>
          <p className="font-medium wrap-anywhere">{named(row)}</p>
          {group === "visit" && row.at ? (
            <p className="text-xs text-muted-foreground">
              {formatDateTime(row.at, locale, zone)}
            </p>
          ) : null}
        </>
      ),
    },
    ...(group === "visit"
      ? ([
          {
            id: "customer",
            header: t("reportRow_customer"),
            enableSorting: false,
            cell: ({ row: { original: row } }) => row.customer_name || "—",
          },
          {
            id: "person",
            header: t("reportRow_person"),
            enableSorting: false,
            cell: ({ row: { original: row } }) => row.person_name || "—",
          },
        ] satisfies ColumnDef<UsageRow, unknown>[])
      : []),
    ...(group === "item"
      ? ([
          {
            id: "quantity",
            header: t("quantity"),
            enableSorting: false,
            meta: { numeric: true },
            cell: ({ row: { original: row } }) =>
              `${amount(row.quantity ?? 0)} ${row.unit ? t(`unit_${row.unit}`) : ""}`,
          },
        ] satisfies ColumnDef<UsageRow, unknown>[])
      : []),
    {
      id: "cost",
      header: t("reportCost"),
      enableSorting: false,
      meta: { numeric: true },
      cell: ({ row: { original: row } }) => money(row.cost_minor, row.currency),
    },
    {
      id: "sold",
      header: t("reportSold"),
      enableSorting: false,
      meta: { numeric: true },
      cell: ({ row: { original: row } }) =>
        row.sold_minor ? money(row.sold_minor, row.currency) : "—",
    },
  ];

  function placeName(id: string) {
    const location = data.locations.find((one) => one.id === id);
    return location ? locationLabel(location) : undefined;
  }

  const toolbar = (
    <>
      <DataTableFilter
        id="report-kind"
        label={t("report")}
        onChange={(event) => choose(event.target.value as Report)}
        value={report}
      >
        <optgroup label={t("reportStock")}>
          {STOCK.map((key) => (
            <option key={key} value={`stock:${key}`}>
              {t(`reportBy_${key}`)}
            </option>
          ))}
        </optgroup>
        <optgroup label={t("reportUsage")}>
          {USAGE.map((key) => (
            <option key={key} value={`usage:${key}`}>
              {t(`reportBy_${key}`)}
            </option>
          ))}
        </optgroup>
      </DataTableFilter>
      {kind === "usage" ? (
        // The period is what the numbers are of: it stays in sight.
        <DataTableFilter
          id="report-period"
          label={t("reportPeriod")}
          onChange={(event) => {
            setPeriod(event.target.value as PeriodKey);
            setQuery((current) => ({ ...current, pageIndex: 0 }));
          }}
          value={period}
        >
          {PERIODS.map((key) => {
            const days = periodDays(key, now, zone);
            return (
              <option key={key} value={key}>
                {periods(`period_${key}`)} ·{" "}
                {formatDateRange(days.from, days.to, locale)}
              </option>
            );
          })}
        </DataTableFilter>
      ) : null}
    </>
  );

  const totals =
    kind === "stock"
      ? (stock?.totals ?? []).map((total) =>
          t("reportTotalValue", {
            value: money(total.value_minor, total.currency),
          }),
        )
      : (usage?.totals ?? []).map((total) =>
          total.sold_minor
            ? t("reportTotalUsageSold", {
                cost: money(total.cost_minor, total.currency),
                sold: money(total.sold_minor, total.currency),
              })
            : t("reportTotalUsage", {
                cost: money(total.cost_minor, total.currency),
              }),
        );

  return (
    <PanelPage
      {...page}
      description={
        kind === "stock"
          ? t("reportStockDescription")
          : t("reportUsageDescription")
      }
    >
      {failed ? (
        <LoadProblemNotice problem={failed} />
      ) : kind === "stock" ? (
        <DataTable
          caption={t("reportStock")}
          columns={stockColumns}
          data={stock?.rows ?? []}
          getRowId={(row) => `${row.key}:${row.currency}`}
          labels={{ ...labels, empty: t("reportStockEmpty") }}
          loading={!stock}
          activeFilters={locationId ? 1 : 0}
          filters={
            <DataTableFilter
              id="report-location"
              label={t("location")}
              onChange={(event) => setLocationId(event.target.value)}
              value={locationId}
            >
              <option value="">{t("allLocations")}</option>
              {data.locations.map((location) => (
                <option key={location.id} value={location.id}>
                  {locationLabel(location)}
                </option>
              ))}
            </DataTableFilter>
          }
          toolbar={toolbar}
        />
      ) : (
        <DataTable
          caption={t("reportUsage")}
          columns={usageColumns}
          data={usage?.rows ?? []}
          getRowId={(row) => `${row.key}:${row.currency}`}
          labels={{ ...labels, empty: t("reportUsageEmpty") }}
          loading={!usage}
          onQueryChange={setQuery}
          pageSize={PAGE}
          query={query}
          rowCount={usage?.total ?? 0}
          toolbar={toolbar}
        />
      )}
      {totals.length ? (
        <p aria-live="polite" className="mt-3 text-sm font-medium">
          {totals.join(" · ")}
        </p>
      ) : null}
    </PanelPage>
  );
}
