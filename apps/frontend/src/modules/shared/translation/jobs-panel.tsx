"use client";

/** „Tłumaczenia → Zadania” (TL16d): every translation order of the company,
 *  a person's and the automation's, newest first — its state, how far it
 *  came and what it cost — with the way to its detail. The list is the
 *  server's: its filter and its pages are asked for. */

import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { ListIcon } from "lucide-react";
import {
  ApiProblemError,
  listTranslationJobs,
  type TranslationJob,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  DataTableFilter,
  FilterSheet,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import { PanelPage } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import {
  JOB_TONE,
  jobActive,
  jobCredits,
  jobProgress,
  jobWaiting,
} from "./job-words";
import { AutomationHeld, HeldDemandTable } from "./held-demand";
import { TranslationTabs } from "./translation-tabs";

type Row = TranslationJob;
/** `held` is not a job's state: what the automation could not start yet. */
type Which = "" | "active" | "ended" | "held";

const PAGE_SIZE = 20;
const POLL_MS = 5000;

type Answer = {
  /** The query this answers; another one is still loading. */
  key: string;
  rows: Row[];
  cursor: string | null;
  at: number;
  problem?: string;
};

export function TranslationJobsPanel({
  initialView = "",
  website = true,
}: {
  /** The view the address asks for: `held` is where a held notice leads. */
  initialView?: "" | "held";
  /** Whether the organization has websites (see `TranslationReviewPanel`). */
  website?: boolean;
}) {
  const t = useTranslations("Translations.jobs");
  const review = useTranslations("Translations.review");
  const nav = useTranslations("DashboardNav");
  const format = useFormatter();
  const labels = useDataTableLabels();
  const [which, setWhich] = useState<Which>(initialView);
  const [answer, setAnswer] = useState<Answer>();
  const [reloads, setReloads] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [problem, setProblem] = useState("");

  const key = `${which}|${reloads}`;
  const query = (cursor?: string) => ({
    limit: PAGE_SIZE,
    ...(which ? { active: which === "active" } : {}),
    ...(cursor ? { cursor } : {}),
  });
  const readProblem = (error: unknown) =>
    error instanceof ApiProblemError && error.problem.status === 403
      ? review("noAccess")
      : t("loadFailed");

  useEffect(() => {
    // „Wstrzymane” lists no jobs: its own table asks for what is held.
    if (which === "held") return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ask = () => {
      listTranslationJobs(query())
        .then((page) => {
          if (!alive) return;
          setAnswer((current) =>
            // A list read further down keeps its length while a job runs.
            current?.key === key && current.rows.length > page.items.length
              ? {
                  ...current,
                  at: Date.now(),
                  rows: current.rows.map(
                    (row) =>
                      page.items.find((fresh) => fresh.id === row.id) ?? row,
                  ),
                }
              : {
                  key,
                  rows: page.items,
                  cursor: page.next_cursor,
                  at: Date.now(),
                },
          );
          // A running job moves: the first page is asked for again.
          if (page.items.some(jobActive)) timer = setTimeout(ask, POLL_MS);
        })
        .catch((error: unknown) => {
          if (alive)
            setAnswer({
              key,
              rows: [],
              cursor: null,
              at: Date.now(),
              problem: readProblem(error),
            });
        });
    };
    ask();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
    // `key` stands for the query and everything that asks for it again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const loading = answer?.key !== key;
  const rows = answer?.rows ?? [];
  const when = (value: string) =>
    format.dateTime(new Date(value), {
      dateStyle: "medium",
      timeStyle: "short",
    });

  async function loadMore(cursor: string) {
    setLoadingMore(true);
    setProblem("");
    try {
      const more = await listTranslationJobs(query(cursor));
      setAnswer((current) =>
        current?.key === key
          ? {
              ...current,
              rows: [...current.rows, ...more.items],
              cursor: more.next_cursor,
            }
          : current,
      );
    } catch (error) {
      setProblem(readProblem(error));
    } finally {
      setLoadingMore(false);
    }
  }

  const columns: ColumnDef<Row, unknown>[] = [
    {
      id: "created",
      accessorKey: "created_at",
      header: t("colCreated"),
      meta: { primary: true, className: "tabular-nums" },
      cell: ({ row: { original: row } }) => (
        <p className="font-medium">{when(row.created_at)}</p>
      ),
    },
    {
      id: "trigger",
      accessorFn: (row) =>
        t(`trigger.${row.trigger === "automatic" ? "automatic" : "click"}`),
      header: t("colTrigger"),
    },
    {
      id: "state",
      accessorKey: "state",
      header: t("colState"),
      meta: { long: true },
      cell: ({ row: { original: row } }) => {
        const waiting = answer ? jobWaiting(row, answer.at) : undefined;
        return (
          <div className="space-y-1">
            <div className="flex flex-wrap gap-1">
              <Badge variant={JOB_TONE[row.state] ?? "neutral"}>
                {t.has(`states.${row.state}`)
                  ? t(`states.${row.state}`)
                  : row.state}
              </Badge>
              {row.reverted_at ? (
                <Badge variant="neutral">{t("reverted")}</Badge>
              ) : null}
            </div>
            {waiting ? (
              <p className="text-xs text-muted-foreground">
                {t(`waiting.${waiting}`, { time: when(row.next_attempt_at) })}
              </p>
            ) : null}
          </div>
        );
      },
    },
    {
      id: "progress",
      accessorFn: (row) => jobProgress(row).done,
      header: t("colProgress"),
      meta: { className: "tabular-nums" },
      cell: ({ row: { original: row } }) => t("progress", jobProgress(row)),
    },
    {
      id: "credits",
      accessorFn: (row) => jobCredits(row).settled,
      header: t("colCredits"),
      meta: { numeric: true },
      cell: ({ row: { original: row } }) =>
        row.billing === "credits" ? jobCredits(row).settled : "—",
    },
    {
      id: "actions",
      header: t("colActions"),
      meta: { actions: true },
      cell: ({ row: { original: row } }) => (
        <RowActions
          items={[
            {
              label: t("details"),
              icon: <ListIcon aria-hidden="true" />,
              inline: true,
              main: true,
              link: <Link href={`/panel/sites/translations/jobs/${row.id}`} />,
            },
          ]}
          label={t("actionsFor", { date: when(row.created_at) })}
        />
      ),
    },
  ];

  const filter = (
    <DataTableFilter
      id="translation-jobs-state"
      label={t("filterState")}
      onChange={(event) => setWhich(event.target.value as Which)}
      value={which}
    >
      <option value="">{t("allStates")}</option>
      <option value="active">{t("active")}</option>
      <option value="ended">{t("ended")}</option>
      <option value="held">{t("held")}</option>
    </DataTableFilter>
  );

  const held = which === "held";
  // One filter for both lists, outside them: „Wstrzymane” swaps the table,
  // and a filter living in the table would close the phone's sheet with it.
  // Hidden like a table's own while there is nothing to narrow (UX-021).
  const narrowable = which !== "" || loading || rows.length > 0;

  return (
    <PanelPage
      description={t("description")}
      eyebrow={nav(website ? "website" : "settings")}
      eyebrowHref={website ? undefined : "/panel/settings"}
      title={review("title")}
    >
      <TranslationTabs website={website} />
      {held ? null : <AutomationHeld />}
      {narrowable ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <FilterSheet active={which ? 1 : 0} labels={labels}>
            {filter}
          </FilterSheet>
        </div>
      ) : null}
      {held ? <HeldDemandTable onClear={() => setWhich("")} /> : null}
      {!held && (problem || (answer?.problem && !loading)) ? (
        <div
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          role="alert"
        >
          <span>{problem || answer?.problem}</span>
          {answer?.problem ? (
            <Button
              onClick={() => setReloads((value) => value + 1)}
              size="sm"
              type="button"
              variant="outline"
            >
              {review("retry")}
            </Button>
          ) : null}
        </div>
      ) : null}
      {held ? null : (
        <DataTable
          activeFilters={which ? 1 : 0}
          caption={t("caption")}
          columns={columns}
          data={rows}
          emptyAction={
            which ? (
              <Button
                onClick={() => setWhich("")}
                type="button"
                variant="outline"
              >
                {review("clearFilters")}
              </Button>
            ) : undefined
          }
          getRowId={(row) => row.id}
          labels={{ ...labels, empty: which ? labels.empty : t("empty") }}
          loading={loading}
          pageSize={PAGE_SIZE}
        />
      )}
      {!held && answer?.cursor && !loading ? (
        <Button
          disabled={loadingMore}
          onClick={() => answer.cursor && void loadMore(answer.cursor)}
          type="button"
          variant="outline"
        >
          {review("loadMore")}
        </Button>
      ) : null}
    </PanelPage>
  );
}
