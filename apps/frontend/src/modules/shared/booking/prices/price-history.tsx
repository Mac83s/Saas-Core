"use client";

import { useCallback, useEffect, useId, useState, type FormEvent } from "react";
import { useLocale, useTranslations } from "next-intl";

import {
  ApiProblemError,
  listBookingPriceChanges,
  readBookingPricesOnDay,
  type BookingPriceChange,
  type BookingPriceChangePage,
  type BookingPriceListOn,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  type ColumnDef,
  type DataTableQuery,
} from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

import { useDataTableLabels } from "#lib/data-table-labels";
import { formatDate, formatDateTime } from "#lib/dates";
import { formatMoney } from "./money";
import { usePriceWords, type PriceSetup } from "./price-book";

const PAGE_SIZE = 10;

/**
 * The record of prices (ADR-073, slice 4i): every write of a price since the
 * record began — who, when, the amount before and after — and the price list
 * as it stood on a chosen day, both read from the server's append-only
 * record. Nothing is edited here.
 */
export function PriceHistoryDialog({
  finalFocus,
  onOpenChange,
  setup,
}: {
  finalFocus?: HTMLElement | null;
  onOpenChange: (open: boolean) => void;
  setup: PriceSetup;
}) {
  const t = useTranslations("PriceHistory");
  const common = useTranslations("Common");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const words = usePriceWords(setup);
  const ids = useId();
  const [query, setQuery] = useState<DataTableQuery>({
    pageIndex: 0,
    pageSize: PAGE_SIZE,
    sorting: [],
    search: "",
  });
  const [page, setPage] = useState<BookingPriceChangePage>();
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [day, setDay] = useState("");
  const [onDay, setOnDay] = useState<BookingPriceListOn>();
  const [dayProblem, setDayProblem] = useState<string>();
  const [asking, setAsking] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      setPage(
        await listBookingPriceChanges({
          page: query.pageIndex + 1,
          pageSize: query.pageSize,
        }),
      );
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [query.pageIndex, query.pageSize]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load on query change
    void load();
  }, [load]);

  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!day) return;
    setAsking(true);
    setDayProblem(undefined);
    setOnDay(undefined);
    try {
      setOnDay(await readBookingPricesOnDay(day));
    } catch (error) {
      setDayProblem(
        error instanceof ApiProblemError
          ? (error.problem.errors?.[0]?.message ?? t("dayFailed"))
          : t("dayFailed"),
      );
    } finally {
      setAsking(false);
    }
  }

  const money = (line: BookingPriceChange, minor: number) =>
    formatMoney(minor, line.currency, locale);
  const what = (line: BookingPriceChange) => {
    const now = money(line, line.amount_minor);
    if (line.change === "updated" && line.previous_amount_minor !== null)
      return line.previous_amount_minor === line.amount_minor
        ? t("updatedSameAmount", { amount: now })
        : t("updated", {
            before: money(line, line.previous_amount_minor),
            after: now,
          });
    return t(`change_${line.change}` as "change_created", { amount: now });
  };

  const columns: ColumnDef<BookingPriceChange, unknown>[] = [
    {
      id: "when",
      header: t("colWhen"),
      enableSorting: false,
      meta: { primary: true },
      cell: ({ row: { original: line } }) => (
        <span className="flex flex-col gap-0.5">
          <span>{formatDateTime(line.recorded_at, locale)}</span>
          <span className="text-sm text-muted-foreground">
            {line.actor
              ? line.acting_via === "assistant"
                ? t("byAssistant", { name: line.actor.name })
                : line.actor.name
              : t(line.change === "baseline" ? "byNobody" : "byUnknown")}
          </span>
        </span>
      ),
    },
    {
      id: "price",
      header: t("colPrice"),
      enableSorting: false,
      cell: ({ row: { original: line } }) => (
        <span className="flex flex-col gap-0.5">
          <span className="font-medium wrap-anywhere">
            {words.title(line.price)}
          </span>
          <span className="text-sm text-muted-foreground">
            {words.scope(line.price)}
          </span>
        </span>
      ),
    },
    {
      id: "change",
      header: t("colChange"),
      enableSorting: false,
      cell: ({ row: { original: line } }) => (
        <span className="tabular-nums">{what(line)}</span>
      ),
    },
  ];

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-3xl"
        closeLabel={common("close")}
        finalFocus={() => finalFocus ?? true}
      >
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>
            {page?.recorded_since
              ? t("description", {
                  since: formatDate(page.recorded_since, locale),
                })
              : t("descriptionEmpty")}
          </DialogDescription>
        </DialogHeader>
        <section aria-labelledby={`${ids}-day-title`} className="space-y-3">
          <h3 className="font-medium" id={`${ids}-day-title`}>
            {t("dayTitle")}
          </h3>
          <form className="flex flex-wrap items-end gap-3" onSubmit={ask}>
            <Field className="max-w-48">
              <FieldLabel htmlFor={`${ids}-day`}>{t("dayLabel")}</FieldLabel>
              <Input
                id={`${ids}-day`}
                onChange={(event) => setDay(event.target.value)}
                type="date"
                value={day}
              />
            </Field>
            <Button disabled={!day || asking} type="submit" variant="outline">
              {t("dayShow")}
            </Button>
          </form>
          {dayProblem ? (
            <p className="text-sm text-destructive" role="alert">
              {dayProblem}
            </p>
          ) : null}
          {onDay ? (
            <div className="space-y-1.5 text-sm" role="status">
              <p className="text-muted-foreground">
                {t("dayAsOf", { moment: formatDateTime(onDay.as_of, locale) })}
              </p>
              {onDay.items.length ? (
                <ul className="list-disc space-y-1 pl-5">
                  {onDay.items.map((rule) => (
                    <li key={rule.id}>
                      {t("dayPrice", {
                        name: words.title(rule),
                        scope: words.scope(rule),
                        amount: words.amount(rule),
                      })}
                      {rule.active ? null : ` · ${t("dayOff")}`}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>{t("dayNone")}</p>
              )}
            </div>
          ) : null}
        </section>
        <section aria-labelledby={`${ids}-changes-title`} className="space-y-3">
          <h3 className="font-medium" id={`${ids}-changes-title`}>
            {t("changesTitle")}
          </h3>
          {failed ? (
            <div className="flex flex-wrap items-center gap-3" role="alert">
              <p className="text-sm text-destructive">{t("loadError")}</p>
              <Button onClick={() => void load()} variant="outline">
                {t("retry")}
              </Button>
            </div>
          ) : (
            <DataTable
              caption={t("changesTitle")}
              columns={columns}
              data={page?.items ?? []}
              getRowId={(line) => line.id}
              labels={{ ...labels, empty: t("none") }}
              loading={loading}
              onQueryChange={setQuery}
              pageSize={PAGE_SIZE}
              query={query}
              rowCount={page?.total ?? 0}
            />
          )}
        </section>
      </DialogContent>
    </Dialog>
  );
}
