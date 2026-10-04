"use client";

/** What the automatic translation of changes is held on (TL16g): changes of
 *  public content it could not start — the consent was lost, the month's
 *  limit or the credits ran out, the engine cannot take work — each with the
 *  reason, when it is tried again and where the cause is lifted. The notice
 *  says it wherever translations are looked at; the list is „Wstrzymane” in
 *  „Zadania”. */

import { useEffect, useState, type ReactNode } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { SettingsIcon } from "lucide-react";
import {
  ApiProblemError,
  listTranslationDemand,
  type TranslationDemand,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import { SOURCE_KINDS } from "./job-words";
import { translationComposed } from "./use-translation";

const PAGE_SIZE = 20;

/** Where each cause is lifted; the rest passes by itself or is the platform's. */
const PLACE: Record<string, "settings" | "credits"> = {
  consent_lost: "settings",
  monthly_limit: "settings",
  credits_exhausted: "credits",
  processing_ack_required: "settings",
};
const PLACE_HREF = {
  settings: "/panel/settings/languages",
  credits: "/panel/settings/credits",
} as const;

/** Why the automation stands still, in the customer's words: its own
 *  reasons, else why translation cannot be ordered at all. */
function useHeldReason() {
  const t = useTranslations("Translations.held.reasons");
  const unavailable = useTranslations("Translations.unavailable");
  return (reason: string) =>
    t.has(reason)
      ? t(reason)
      : unavailable.has(reason) && reason !== "line"
        ? unavailable(reason)
        : t("other");
}

/** One line where translations are looked at: the automation is held, why,
 *  and the way to what waits. Nothing while nothing is held. */
export function AutomationHeld({
  reloadKey = "",
}: {
  /** Changes when what is held may have changed: asked again. */
  reloadKey?: string | number;
}) {
  const t = useTranslations("Translations.held");
  const reasonText = useHeldReason();
  const [held, setHeld] = useState<{ count: number; reason: string }>();

  useEffect(() => {
    // No engine in this deployment: no automation to ask about.
    if (!translationComposed()) return;
    let alive = true;
    listTranslationDemand({ state: "blocked", limit: 1 })
      .then((page) => {
        if (!alive) return;
        setHeld(
          page.count > 0
            ? { count: page.count, reason: page.items[0]?.reason ?? "" }
            : undefined,
        );
      })
      .catch(() => {
        // Not this person's to see, or no answer: no notice.
        if (alive) setHeld(undefined);
      });
    return () => {
      alive = false;
    };
  }, [reloadKey]);

  if (!held) return null;
  return (
    <p
      className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-lg border border-warning-foreground/30 bg-warning p-3 text-sm text-warning-foreground"
      role="status"
    >
      <span>
        {t("notice", { count: held.count, reason: reasonText(held.reason) })}
      </span>
      <Link
        className="font-medium underline underline-offset-2"
        href="/panel/sites/translations/jobs?state=held"
      >
        {t("show")}
      </Link>
    </p>
  );
}

type Answer = {
  key: number;
  rows: TranslationDemand[];
  cursor: string | null;
  problem?: string;
};

/** „Wstrzymane”: the list itself, under the filter of „Zadania”. */
export function HeldDemandTable({
  filters,
  onClear,
}: {
  /** The filter of „Zadania”, which chose this view. */
  filters: ReactNode;
  onClear: () => void;
}) {
  const t = useTranslations("Translations.held");
  const review = useTranslations("Translations.review");
  const reasonText = useHeldReason();
  const format = useFormatter();
  const labels = useDataTableLabels();
  const [answer, setAnswer] = useState<Answer>();
  const [reloads, setReloads] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);

  const readProblem = (error: unknown) =>
    error instanceof ApiProblemError && error.problem.status === 403
      ? review("noAccess")
      : t("loadFailed");

  useEffect(() => {
    let alive = true;
    listTranslationDemand({ state: "blocked", limit: PAGE_SIZE })
      .then((page) => {
        if (alive)
          setAnswer({
            key: reloads,
            rows: page.items,
            cursor: page.next_cursor,
          });
      })
      .catch((error: unknown) => {
        if (alive)
          setAnswer({
            key: reloads,
            rows: [],
            cursor: null,
            problem: readProblem(error),
          });
      });
    return () => {
      alive = false;
    };
    // Asked once, and again on „Spróbuj ponownie”.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloads]);

  const loading = answer?.key !== reloads;

  async function loadMore(cursor: string) {
    setLoadingMore(true);
    try {
      const more = await listTranslationDemand({
        state: "blocked",
        limit: PAGE_SIZE,
        cursor,
      });
      setAnswer((current) =>
        current
          ? {
              ...current,
              rows: [...current.rows, ...more.items],
              cursor: more.next_cursor,
            }
          : current,
      );
    } catch (error) {
      setAnswer((current) =>
        current ? { ...current, problem: readProblem(error) } : current,
      );
    } finally {
      setLoadingMore(false);
    }
  }

  const when = (value: string) =>
    format.dateTime(new Date(value), {
      dateStyle: "medium",
      timeStyle: "short",
    });
  const kindOf = (row: TranslationDemand) =>
    review(`kinds.${SOURCE_KINDS[row.source_key] ?? "other"}`);
  const nameOf = (row: TranslationDemand) => row.label || kindOf(row);

  const columns: ColumnDef<TranslationDemand, unknown>[] = [
    {
      id: "what",
      accessorFn: nameOf,
      header: t("colWhat"),
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <>
          <p className="font-medium wrap-anywhere">{nameOf(row)}</p>
          {row.label ? (
            <p className="text-xs text-muted-foreground">{kindOf(row)}</p>
          ) : null}
        </>
      ),
    },
    {
      id: "reason",
      accessorFn: (row) => reasonText(row.reason),
      header: t("colReason"),
      meta: { long: true },
    },
    {
      id: "since",
      accessorKey: "first_at",
      header: t("colSince"),
      meta: { className: "tabular-nums" },
      cell: ({ row: { original: row } }) => when(row.first_at),
    },
    {
      id: "check",
      accessorKey: "check_at",
      header: t("colCheck"),
      meta: { className: "tabular-nums" },
      cell: ({ row: { original: row } }) =>
        row.check_at ? when(row.check_at) : "—",
    },
    {
      id: "actions",
      header: t("colActions"),
      meta: { actions: true },
      cell: ({ row: { original: row } }) => {
        const place = PLACE[row.reason];
        return place ? (
          <RowActions
            items={[
              {
                label: t(`place.${place}`),
                icon: <SettingsIcon aria-hidden="true" />,
                inline: true,
                main: true,
                link: <Link href={PLACE_HREF[place]} />,
              },
            ]}
            label={t("actionsFor", { name: nameOf(row) })}
          />
        ) : null;
      },
    },
  ];

  return (
    <>
      <p className="max-w-3xl text-sm text-muted-foreground">{t("hint")}</p>
      {answer?.problem && !loading ? (
        <div
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          role="alert"
        >
          <span>{answer.problem}</span>
          <Button
            onClick={() => setReloads((value) => value + 1)}
            size="sm"
            type="button"
            variant="outline"
          >
            {review("retry")}
          </Button>
        </div>
      ) : null}
      <DataTable
        activeFilters={1}
        caption={t("caption")}
        columns={columns}
        data={answer?.rows ?? []}
        emptyAction={
          <Button onClick={onClear} type="button" variant="outline">
            {review("clearFilters")}
          </Button>
        }
        filters={filters}
        getRowId={(row) => row.id}
        labels={{ ...labels, empty: t("empty") }}
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
          {review("loadMore")}
        </Button>
      ) : null}
    </>
  );
}
