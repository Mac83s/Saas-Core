"use client";

import { useCallback, useEffect, useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";

import {
  ApiProblemError,
  getStaffFacts,
  getStaffHistory,
  listInventoryBalances,
  type InventoryBalance,
  type StaffEvent,
  type StaffFacts,
  type StaffMetric,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  DataTableFilter,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";

import { PanelSection } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";
import { formatDateRange } from "#lib/dates";
import { addDays, addMonths, wallClock } from "../calendar-time";

/**
 * A person's results and history (team plan, phase 5, boards 4, 5 and 7).
 * Each module counts its own; the card only says them. Somebody else's are
 * the owner's and administrator's (owner's answer 3); the API refuses the
 * rest, and a refused card shows nothing rather than an error.
 */

export const PERIODS = ["month", "previous", "quarter", "year"] as const;
export type PeriodKey = (typeof PERIODS)[number];

/** The period's days in the organization's zone. */
export function periodDays(
  key: PeriodKey,
  now: Date,
  zone: string,
): { from: string; to: string } {
  const today = wallClock(now, zone).day;
  const month = `${today.slice(0, 7)}-01`;
  switch (key) {
    case "previous":
      return { from: addMonths(month, -1), to: addDays(month, -1) };
    case "quarter":
      return { from: addDays(today, -89), to: today };
    case "year":
      return { from: `${today.slice(0, 4)}-01-01`, to: today };
    default:
      return { from: month, to: today };
  }
}

/** A module's word for its group and its numbers; a product's own too. */
export function useFactWords() {
  const t = useTranslations("StaffFacts");
  const words = (key: string) =>
    key.charAt(0).toUpperCase() + key.slice(1).replaceAll("_", " ");
  return {
    provider: (name: string) =>
      t.has(`provider.${name}`) ? t(`provider.${name}`) : words(name),
    metric: (provider: string, key: string) =>
      t.has(`metric.${provider}.${key}`)
        ? t(`metric.${provider}.${key}`)
        : words(key),
  };
}

/** "88 h", "1 868,40 zł" or "19", as the number's unit says. */
export function useFactValue(currency: string) {
  const format = useFormatter();
  const t = useTranslations("StaffFacts");
  return (value: number, unit: string) => {
    if (unit === "minutes")
      return t("hours", {
        hours: format.number(value / 60, { maximumFractionDigits: 1 }),
      });
    if (unit === "money")
      return format.number(value / 100, { style: "currency", currency });
    return format.number(value);
  };
}

function refused(error: unknown) {
  return (
    error instanceof ApiProblemError &&
    [403, 404].includes(error.problem.status ?? 0)
  );
}

function PeriodFilter({
  id,
  value,
  onChange,
}: {
  id: string;
  value: PeriodKey;
  onChange: (value: PeriodKey) => void;
}) {
  const t = useTranslations("StaffFacts");
  return (
    <DataTableFilter
      id={id}
      label={t("period")}
      onChange={(event) => onChange(event.target.value as PeriodKey)}
      value={value}
    >
      {PERIODS.map((key) => (
        <option key={key} value={key}>
          {t(`period_${key}`)}
        </option>
      ))}
    </DataTableFilter>
  );
}

/** Przegląd › Wyniki: every module's numbers beside the period before. */
export function PersonResults({
  staffId,
  zone,
  currency,
}: {
  staffId: string;
  zone: string;
  currency: string;
}) {
  const t = useTranslations("StaffFacts");
  const locale = useLocale();
  const words = useFactWords();
  const value = useFactValue(currency);
  const [now] = useState(() => new Date());
  const [period, setPeriod] = useState<PeriodKey>("month");
  const [facts, setFacts] = useState<StaffFacts | null>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let current = true;
    getStaffFacts(staffId, periodDays(period, now, zone)).then(
      (next) => {
        if (!current) return;
        setFacts(next);
        setFailed(false);
      },
      (error: unknown) => {
        if (!current) return;
        if (refused(error)) setFacts(null);
        else setFailed(true);
      },
    );
    return () => {
      current = false;
    };
  }, [now, period, staffId, zone]);

  if (facts === null) return null;
  const range = (from: string, to: string) => formatDateRange(from, to, locale);
  const previous = (metric: StaffMetric) =>
    metric.previous === null
      ? null
      : t("previous", { value: value(metric.previous, metric.unit) });

  return (
    <PanelSection
      actions={
        <PeriodFilter id="results-period" onChange={setPeriod} value={period} />
      }
      description={t("privacy")}
      title={t("title")}
    >
      {failed ? (
        <p className="text-sm text-destructive" role="alert">
          {t("loadError")}
        </p>
      ) : !facts ? (
        <div
          aria-busy="true"
          className="h-32 animate-pulse rounded-xl bg-muted"
        >
          <span className="sr-only">{t("loading")}</span>
        </div>
      ) : (
        <div className="space-y-5">
          <p className="text-sm text-muted-foreground">
            {range(facts.period_from, facts.period_to)}
          </p>
          {facts.groups.length ? null : (
            <p className="text-sm text-muted-foreground">{t("nothing")}</p>
          )}
          {facts.groups.map((group) =>
            group.metrics.every(
              (metric) => !metric.value && !metric.previous,
            ) ? (
              // A group of zeros is one line, not a screen of tiles (UX-034).
              <p className="text-sm text-muted-foreground" key={group.provider}>
                <span className="font-semibold text-foreground">
                  {words.provider(group.provider)}
                </span>
                {": "}
                {t("quiet")}
              </p>
            ) : (
              <section
                aria-labelledby={`facts-${group.provider}`}
                className="space-y-2"
                key={group.provider}
              >
                <h3
                  className="text-sm font-semibold"
                  id={`facts-${group.provider}`}
                >
                  {words.provider(group.provider)}
                </h3>
                <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  {group.metrics.map((metric) => (
                    <div
                      className="min-w-0 rounded-xl border p-3"
                      key={metric.key}
                    >
                      <dt className="text-sm text-muted-foreground">
                        {words.metric(group.provider, metric.key)}
                      </dt>
                      <dd className="text-lg font-semibold tabular-nums sm:text-2xl">
                        {value(metric.value, metric.unit)}
                      </dd>
                      {metric.key === "visits_done" &&
                      group.provider === "calendar" ? (
                        <dd className="text-xs text-muted-foreground">
                          {t("visitParts", {
                            lead: metric.parts.lead ?? 0,
                            crew: metric.parts.crew ?? 0,
                          })}
                        </dd>
                      ) : null}
                      {previous(metric) ? (
                        <dd className="text-xs text-muted-foreground">
                          {previous(metric)}
                        </dd>
                      ) : null}
                    </div>
                  ))}
                </dl>
              </section>
            ),
          )}
        </div>
      )}
    </PanelSection>
  );
}

/** Karta › Historia: what happened, newest first, a page at a time. */
export function PersonHistory({
  staffId,
  zone,
  currency,
}: {
  staffId: string;
  zone: string;
  currency: string;
}) {
  const t = useTranslations("StaffFacts");
  const format = useFormatter();
  const labels = useDataTableLabels();
  const words = useFactWords();
  const value = useFactValue(currency);
  const [now] = useState(() => new Date());
  const [period, setPeriod] = useState<PeriodKey>("month");
  const [kind, setKind] = useState("");
  const [kinds, setKinds] = useState<string[]>([]);
  const [items, setItems] = useState<StaffEvent[]>();
  const [older, setOlder] = useState<string | null>(null);
  const [problem, setProblem] = useState<"access" | "load">();

  const fetchPage = useCallback(
    (before?: string) =>
      getStaffHistory(staffId, {
        ...periodDays(period, now, zone),
        ...(kind ? { kind } : {}),
        ...(before ? { before } : {}),
      }),
    [kind, now, period, staffId, zone],
  );

  useEffect(() => {
    let current = true;
    fetchPage().then(
      (page) => {
        if (!current) return;
        setItems(page.items);
        setKinds(page.kinds);
        setOlder(page.next_before);
        setProblem(undefined);
      },
      (error: unknown) => {
        if (current) setProblem(refused(error) ? "access" : "load");
      },
    );
    return () => {
      current = false;
    };
  }, [fetchPage]);

  const when = (at: string) =>
    format.dateTime(new Date(at), {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: zone,
    });
  const details = (item: StaffEvent) => {
    const params = item.params as Record<string, unknown>;
    const text = (key: string) => String(params[key] ?? "");
    switch (item.event) {
      case "visit_done":
        return t("detail.visit", {
          customer: text("customer"),
          service: text("service"),
          role: text("role"),
        });
      case "assigned":
      case "unassigned":
        return [
          text("customer"),
          params.starts_at ? when(text("starts_at")) : "",
          params.by ? t("detail.by", { name: text("by") }) : "",
        ]
          .filter(Boolean)
          .join(" · ");
      case "time_off":
        return [`${when(text("from"))} – ${when(text("to"))}`, text("reason")]
          .filter(Boolean)
          .join(" · ");
      case "role_changed":
        return [
          `${text("from_name") || text("from")} → ${text("to_name") || text("to")}`,
          params.by ? t("detail.by", { name: text("by") }) : "",
        ]
          .filter(Boolean)
          .join(" · ");
      case "taken":
      case "used":
      case "returned":
        return [
          text("number"),
          ((params.lines as { name: string; quantity: string }[]) ?? [])
            .map((line) => `${line.quantity}× ${line.name}`)
            .join(", "),
        ]
          .filter(Boolean)
          .join(" · ");
      default: {
        // A product's own event reads through its own words: its messages
        // give `StaffFacts.detail.<provider>.<event>` over the params.
        const key = `detail.${item.kind}.${item.event}`;
        if (!t.has(key)) return "";
        const values = Object.fromEntries(
          Object.entries(params).filter(
            (entry): entry is [string, string | number] =>
              typeof entry[1] === "string" || typeof entry[1] === "number",
          ),
        );
        return t(key, values);
      }
    }
  };
  const eventLabel = (item: StaffEvent) =>
    t.has(`event.${item.kind}.${item.event}`)
      ? t(`event.${item.kind}.${item.event}`)
      : t.has(`event.${item.event}`)
        ? t(`event.${item.event}`)
        : item.event;

  const columns: ColumnDef<StaffEvent, unknown>[] = [
    {
      id: "at",
      accessorFn: (item) => new Date(item.at),
      header: t("column.at"),
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <span className="tabular-nums">{when(item.at)}</span>
      ),
    },
    {
      id: "event",
      accessorFn: eventLabel,
      header: t("column.event"),
      cell: ({ row: { original: item } }) => (
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{eventLabel(item)}</span>
          <Badge variant="secondary">{words.provider(item.kind)}</Badge>
        </span>
      ),
    },
    {
      id: "details",
      accessorFn: details,
      header: t("column.details"),
      cell: ({ row: { original: item } }) => (
        <span className="wrap-anywhere">{details(item)}</span>
      ),
    },
    {
      id: "value",
      accessorFn: (item) => item.value ?? 0,
      header: t("column.value"),
      cell: ({ row: { original: item } }) =>
        item.value === null ? "—" : value(item.value, item.unit),
    },
  ];

  if (problem === "access") return null;
  return (
    <PanelSection description={t("historyIntro")} title={t("historyTitle")}>
      {problem === "load" ? (
        <p className="text-sm text-destructive" role="alert">
          {t("loadError")}
        </p>
      ) : (
        <DataTable
          caption={t("historyCaption")}
          columns={columns}
          data={items ?? []}
          labels={{ ...labels, empty: t("historyEmpty") }}
          loading={!items}
          pageSize={100}
          toolbar={
            <PeriodFilter
              id="history-period"
              onChange={setPeriod}
              value={period}
            />
          }
          activeFilters={kind ? 1 : 0}
          filters={
            <DataTableFilter
              id="history-kind"
              label={t("kind")}
              onChange={(event) => setKind(event.target.value)}
              value={kind}
            >
              <option value="">{t("kindAll")}</option>
              {kinds.map((name) => (
                <option key={name} value={name}>
                  {words.provider(name)}
                </option>
              ))}
            </DataTableFilter>
          }
        />
      )}
      {older ? (
        <Button
          onClick={() =>
            void fetchPage(older).then(
              (page) => {
                setItems((current) => [...(current ?? []), ...page.items]);
                setOlder(page.next_before);
              },
              () => setProblem("load"),
            )
          }
          variant="outline"
        >
          {t("older")}
        </Button>
      ) : null}
    </PanelSection>
  );
}

/** Karta › Magazyn: what the person holds now; its value is on Przegląd. */
export function PersonStock({
  holderId,
  own,
}: {
  holderId?: string;
  own: boolean;
}) {
  const t = useTranslations("StaffFacts");
  // The stock tabs' unit names: "szt.", not the API's "piece".
  const units = useTranslations("Inventory");
  const labels = useDataTableLabels();
  const format = useFormatter();
  const [rows, setRows] = useState<InventoryBalance[]>();
  const [problem, setProblem] = useState<"access" | "load">();

  useEffect(() => {
    let current = true;
    listInventoryBalances(own ? { mine: true } : { holderId }).then(
      (next) => {
        if (current) setRows(next);
      },
      (error: unknown) => {
        if (current) setProblem(refused(error) ? "access" : "load");
      },
    );
    return () => {
      current = false;
    };
  }, [holderId, own]);

  const columns: ColumnDef<InventoryBalance, unknown>[] = [
    {
      id: "item",
      accessorFn: (row) => row.item_name,
      header: t("stock.item"),
      meta: { primary: true },
    },
    {
      id: "quantity",
      accessorFn: (row) => Number(row.quantity),
      header: t("stock.quantity"),
      cell: ({ row: { original: row } }) =>
        `${format.number(Number(row.quantity))} ${units(`unit_${row.unit}`)}`,
      meta: { numeric: true },
    },
  ];

  if (problem === "access") return null;
  return (
    <PanelSection description={t("stock.intro")} title={t("stock.title")}>
      {problem === "load" ? (
        <p className="text-sm text-destructive" role="alert">
          {t("loadError")}
        </p>
      ) : (
        <DataTable
          caption={t("stock.title")}
          columns={columns}
          data={rows ?? []}
          getRowId={(row) => row.item_id}
          labels={{ ...labels, empty: t("stock.empty") }}
          loading={!rows}
          searchable
        />
      )}
    </PanelSection>
  );
}
