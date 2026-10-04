"use client";

import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { ListChecksIcon } from "lucide-react";

import {
  listCreditLedger,
  type CreditLedgerEntry,
  type CreditLedgerQuery,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  DataTableFilter,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";

import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import { SectionHeader } from "./parts";

const PAGE_SIZE = 25;

/** What the list shows: what was used, or every movement of credits. */
type Shown = "consumed" | "all";

/** Where a row's `subject` is opened. Billing knows the kinds by name only:
 *  the module that owns the operation says what a row was for. */
const SUBJECT_HREF: Record<string, (id: string) => string> = {
  "translation.job": (id) => `/panel/sites/translations/jobs/${id}`,
};

type Answer = {
  /** The query this answers; another one is still loading. */
  key: string;
  rows: CreditLedgerEntry[];
  cursor: string | null;
  problem?: boolean;
};

/**
 * „Zużycie” on the credits page (TL16f): what the credits went on — the
 * operation, its amount (thousands of characters for a translation), the
 * credits, the pool they came from and when — newest first, a page at a
 * time. A translation's row leads to its job.
 */
export function CreditUsage() {
  const t = useTranslations("Credits.usage");
  const format = useFormatter();
  const labels = useDataTableLabels();
  const [shown, setShown] = useState<Shown>("consumed");
  const [answer, setAnswer] = useState<Answer>();
  const [reloads, setReloads] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);

  const key = `${shown}|${reloads}`;
  const query = (cursor?: string): CreditLedgerQuery => ({
    limit: PAGE_SIZE,
    ...(shown === "consumed" ? { kind: "consumed" as const } : {}),
    ...(cursor ? { cursor } : {}),
  });

  useEffect(() => {
    let alive = true;
    listCreditLedger(query())
      .then((page) => {
        if (alive)
          setAnswer({ key, rows: page.items, cursor: page.next_cursor });
      })
      .catch(() => {
        if (alive) setAnswer({ key, rows: [], cursor: null, problem: true });
      });
    return () => {
      alive = false;
    };
    // `key` stands for the query and everything that asks for it again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  async function loadMore(cursor: string) {
    setLoadingMore(true);
    try {
      const more = await listCreditLedger(query(cursor));
      setAnswer((current) =>
        current?.key === key
          ? {
              ...current,
              rows: [...current.rows, ...more.items],
              cursor: more.next_cursor,
              problem: false,
            }
          : current,
      );
    } catch {
      setAnswer((current) =>
        current?.key === key ? { ...current, problem: true } : current,
      );
    } finally {
      setLoadingMore(false);
    }
  }

  const loading = answer?.key !== key;
  const when = (value: string) =>
    format.dateTime(new Date(value), {
      dateStyle: "medium",
      timeStyle: "short",
    });
  /** The operation in the reader's words; one the panel does not know yet
   *  keeps the catalogue's own name. */
  const operation = (row: CreditLedgerEntry) => {
    const name = `operations.${row.operation_key.replaceAll(".", "_")}`;
    return t.has(name) ? t(name) : row.operation_name || row.operation_key;
  };
  const what = (row: CreditLedgerEntry) =>
    row.kind === "consumed"
      ? operation(row)
      : row.kind === "refunded"
        ? t("kinds.refunded", { operation: operation(row) })
        : t.has(`kinds.${row.kind}`)
          ? t(`kinds.${row.kind}`)
          : t("kinds.other");
  const amount = (row: CreditLedgerEntry) =>
    !row.operation_quantity
      ? "—"
      : row.operation_unit === "1000_characters"
        ? t("thousandCharacters", { count: row.operation_quantity })
        : row.operation_quantity > 1
          ? t("times", { count: row.operation_quantity })
          : "—";
  const subjectHref = (row: CreditLedgerEntry) =>
    row.subject ? SUBJECT_HREF[row.subject.kind]?.(row.subject.id) : undefined;

  const columns: ColumnDef<CreditLedgerEntry, unknown>[] = [
    {
      id: "what",
      accessorFn: what,
      header: t("colWhat"),
      enableSorting: false,
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <div className="space-y-0.5">
          <p className="font-medium">{what(row)}</p>
          {row.reason ? (
            <p className="text-xs text-muted-foreground wrap-anywhere">
              {row.reason}
            </p>
          ) : null}
        </div>
      ),
    },
    {
      id: "amount",
      accessorFn: amount,
      header: t("colAmount"),
      enableSorting: false,
    },
    {
      id: "credits",
      accessorKey: "amount",
      header: t("colCredits"),
      enableSorting: false,
      meta: { numeric: true },
      cell: ({ row: { original: row } }) => (
        <span className="tabular-nums">
          {row.amount > 0
            ? `+${format.number(row.amount)}`
            : `−${format.number(-row.amount)}`}
        </span>
      ),
    },
    {
      id: "bucket",
      accessorFn: (row) =>
        t.has(`bucket.${row.bucket}`) ? t(`bucket.${row.bucket}`) : row.bucket,
      header: t("colBucket"),
      enableSorting: false,
    },
    {
      id: "date",
      accessorKey: "occurred_at",
      header: t("colDate"),
      enableSorting: false,
      meta: { className: "tabular-nums" },
      cell: ({ row: { original: row } }) => when(row.occurred_at),
    },
    {
      id: "actions",
      header: t("colActions"),
      meta: { actions: true },
      cell: ({ row: { original: row } }) => {
        const href = subjectHref(row);
        return href ? (
          <RowActions
            items={[
              {
                label: t("openJob"),
                icon: <ListChecksIcon aria-hidden="true" />,
                inline: true,
                main: true,
                link: <Link href={href} />,
              },
            ]}
            label={t("actionsFor", {
              what: what(row),
              date: when(row.occurred_at),
            })}
          />
        ) : null;
      },
    },
  ];

  return (
    <section aria-labelledby="credit-usage-heading" className="space-y-4">
      <SectionHeader
        description={t("description")}
        id="credit-usage-heading"
        title={t("title")}
      />
      {answer?.problem && !loading ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{t("loadError")}</p>
          <Button
            onClick={() => setReloads((value) => value + 1)}
            size="sm"
            type="button"
            variant="outline"
          >
            {t("retry")}
          </Button>
        </div>
      ) : null}
      <DataTable
        // „Zużycie” is the narrowed view: with nothing used yet the way to
        // every movement stays in sight.
        activeFilters={shown === "consumed" ? 1 : 0}
        caption={t("title")}
        columns={columns}
        data={answer?.rows ?? []}
        filters={
          <DataTableFilter
            id="credit-usage-shown"
            label={t("filterShown")}
            onChange={(event) => setShown(event.target.value as Shown)}
            value={shown}
          >
            <option value="consumed">{t("shownConsumed")}</option>
            <option value="all">{t("shownAll")}</option>
          </DataTableFilter>
        }
        getRowId={(row) => row.id}
        labels={{
          ...labels,
          empty: t(shown === "consumed" ? "emptyConsumed" : "emptyAll"),
        }}
        loading={loading}
        pageSize={PAGE_SIZE}
      />
      {answer?.cursor && !loading ? (
        <Button
          disabled={loadingMore}
          onClick={() => answer.cursor && void loadMore(answer.cursor)}
          type="button"
          variant="outline"
        >
          {t("loadMore")}
        </Button>
      ) : null}
    </section>
  );
}
