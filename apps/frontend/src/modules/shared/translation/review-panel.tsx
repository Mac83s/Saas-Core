"use client";

/** „Tłumaczenia → Do akceptacji” (TL16): what the engine delivered and a
 *  person has to decide — why each result waits, in which language, since
 *  when — with the decision itself: accept (it goes out the way its source
 *  publishes) or discard. Deciding is a person's click, one item or the
 *  marked ones together; the server checks the versions the person saw. */

import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { CheckIcon, PencilIcon, XIcon } from "lucide-react";
import {
  ApiProblemError,
  decideTranslationReview,
  listTranslationReview,
  type TranslationReviewItem,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  DataTableFilter,
  RowActions,
  type ColumnDef,
  type RowAction,
} from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { PanelPage } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { nativeName } from "#lib/company-locales";
import { useDataTableLabels } from "#lib/data-table-labels";
import { TranslationTabs } from "./translation-tabs";

type Row = TranslationReviewItem;

const PAGE_SIZE = 50;

/** The reasons a filter offers, most common first. */
const REASONS = [
  "review_mode",
  "overwrites_human",
  "locale_first_appearance",
  "legal_document",
  "qa_flagged",
  "mass_publication",
  "publisher_required",
  "operator_forced_review",
  "source_withdrawn",
  "qa_failed",
  "gate_failed",
  "model_refused",
] as const;

/** What each source's object is called in the panel. */
const KINDS: Record<string, string> = {
  "sites.page": "page",
  "sites.entry": "entry",
  "sites.site_texts": "siteTexts",
  "profiles.public_profile": "profile",
  "booking.catalog": "catalog",
};

/** Where the waiting text can be read and changed by hand. */
function placeOf(row: Row): string | undefined {
  switch (row.source_key) {
    case "sites.page":
      return `/panel/sites/pages/${row.object_id}?language=${row.locale}`;
    case "sites.entry":
      return row.scope
        ? `/panel/sites/blog?site=${row.scope}`
        : "/panel/sites/blog";
    case "profiles.public_profile":
      return "/panel/profile";
    case "booking.catalog":
      return "/panel/settings/services";
    default:
      return undefined;
  }
}

/** The source was taken off the site: "accepting" takes the translation down
 *  with it, so it is its own decision with its own words, never a bulk one. */
const withdrawal = (row: Row) => row.reason === "source_withdrawn";
const bulkable = (row: Row) => row.acceptable && !withdrawal(row);

type Answer = {
  /** The query this answers; another one is still loading. */
  key: string;
  rows: Row[];
  cursor: string | null;
  problem?: string;
};

type Decision = {
  action: "accept" | "discard";
  rows: Row[];
  /** One key per decision asked: a repeated click answers the first result. */
  key: string;
};

export function TranslationReviewPanel() {
  const t = useTranslations("Translations.review");
  const nav = useTranslations("DashboardNav");
  const skipped = useTranslations("Sites.languageMode.skipped");
  const format = useFormatter();
  const labels = useDataTableLabels();
  const [reason, setReason] = useState("");
  const [answer, setAnswer] = useState<Answer>();
  // Everything that waits, whatever the filter shows: the tab's number.
  const [waiting, setWaiting] = useState(0);
  const [reloads, setReloads] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [deciding, setDeciding] = useState<Decision>();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState("");
  const [dialogProblem, setDialogProblem] = useState("");

  const key = `${reason}|${reloads}`;
  const query = (cursor?: string) => ({
    limit: PAGE_SIZE,
    ...(reason ? { reason } : {}),
    ...(cursor ? { cursor } : {}),
  });
  const readProblem = (error: unknown) =>
    error instanceof ApiProblemError && error.problem.status === 403
      ? t("noAccess")
      : t("loadFailed");

  useEffect(() => {
    let alive = true;
    listTranslationReview(query())
      .then((page) => {
        if (!alive) return;
        setAnswer({ key, rows: page.items, cursor: page.next_cursor });
        if (!reason) setWaiting(page.count);
      })
      .catch((error: unknown) => {
        if (alive)
          setAnswer({
            key,
            rows: [],
            cursor: null,
            problem: readProblem(error),
          });
      });
    return () => {
      alive = false;
    };
    // `key` stands for the query and everything that asks for it again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const loading = answer?.key !== key;
  const rows = answer?.rows ?? [];
  const marked = rows.filter((row) => selected.has(row.id) && bulkable(row));
  const markable = rows.filter(bulkable);

  const kindOf = (row: Row) => t(`kinds.${KINDS[row.source_key] ?? "other"}`);
  const nameOf = (row: Row) => row.label || kindOf(row);
  const reasonOf = (row: Row) =>
    t.has(`reasons.${row.reason}`)
      ? t(`reasons.${row.reason}`)
      : t("reasons.other");

  async function loadMore(cursor: string) {
    setLoadingMore(true);
    try {
      const more = await listTranslationReview(query(cursor));
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

  function ask(action: Decision["action"], chosen: Row[]) {
    setDialogProblem("");
    setDeciding({ action, rows: chosen, key: crypto.randomUUID() });
  }

  function reload() {
    setSelected(new Set());
    setReloads((value) => value + 1);
  }

  async function decide(decision: Decision) {
    setBusy(true);
    setDialogProblem("");
    setProblem("");
    setNotice("");
    try {
      const result = await decideTranslationReview(
        decision.action,
        decision.rows,
        decision.key,
      );
      const count = decision.rows.length;
      // Accepted, but its source could not put it out yet — with the reason.
      const held = result.items
        .flatMap((item) => item.outcomes)
        .find((outcome) => outcome.state === "pending");
      const why = typeof held?.reason === "string" ? held.reason : "other";
      setNotice(
        decision.action === "discard"
          ? t(decision.rows.every(withdrawal) ? "kept" : "discarded", { count })
          : decision.rows.every(withdrawal)
            ? t("withdrawn", { count })
            : held
              ? t("acceptedNotPublished", {
                  count,
                  reason: skipped.has(why) ? skipped(why) : skipped("other"),
                })
              : t("accepted", { count }),
      );
      setDeciding(undefined);
      // Decided rows leave at once — the list asked for again confirms it.
      const decided = new Set(decision.rows.map((row) => row.id));
      setAnswer((current) =>
        current
          ? {
              ...current,
              rows: current.rows.filter((row) => !decided.has(row.id)),
            }
          : current,
      );
      setWaiting((value) => Math.max(0, value - decided.size));
      reload();
    } catch (error) {
      const code =
        error instanceof ApiProblemError ? error.problem.code : undefined;
      if (code === "translation_review_changed") {
        // Somebody decided it meanwhile, or a newer result replaced it.
        setProblem(t("changed"));
        setDeciding(undefined);
        reload();
      } else
        setDialogProblem(
          error instanceof ApiProblemError && error.problem.status === 403
            ? t("forbidden")
            : t("failed"),
        );
    } finally {
      setBusy(false);
    }
  }

  const toggle = (row: Row, on: boolean) =>
    setSelected((current) => {
      const next = new Set(current);
      if (on) next.add(row.id);
      else next.delete(row.id);
      return next;
    });

  // Marks exist only while something here can be accepted together.
  const selectColumn: ColumnDef<Row, unknown>[] =
    markable.length === 0
      ? []
      : [
          {
            id: "select",
            enableSorting: false,
            meta: { label: t("colSelect") },
            header: () => (
              <input
                aria-label={t("selectAll")}
                checked={marked.length === markable.length}
                className="size-4"
                onChange={(event) =>
                  setSelected(
                    new Set(
                      event.target.checked ? markable.map((row) => row.id) : [],
                    ),
                  )
                }
                type="checkbox"
              />
            ),
            cell: ({ row: { original: row } }) =>
              bulkable(row) ? (
                <input
                  aria-label={t("select", {
                    name: nameOf(row),
                    language: nativeName(row.locale),
                  })}
                  checked={selected.has(row.id)}
                  className="size-4"
                  onChange={(event) => toggle(row, event.target.checked)}
                  type="checkbox"
                />
              ) : (
                "—"
              ),
          },
        ];
  const columns: ColumnDef<Row, unknown>[] = [
    ...selectColumn,
    {
      id: "what",
      accessorFn: nameOf,
      header: t("colWhat"),
      meta: { primary: true, className: "max-md:order-first" },
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
      id: "language",
      accessorFn: (row) => nativeName(row.locale),
      header: t("colLanguage"),
    },
    {
      id: "reason",
      accessorFn: reasonOf,
      header: t("colReason"),
      meta: { long: true },
    },
    {
      id: "keys",
      accessorKey: "keys",
      header: t("colKeys"),
      meta: { numeric: true },
    },
    {
      id: "created",
      accessorKey: "created_at",
      header: t("colCreated"),
      meta: { className: "tabular-nums" },
      cell: ({ row: { original: row } }) =>
        format.dateTime(new Date(row.created_at), {
          dateStyle: "medium",
          timeStyle: "short",
        }),
    },
    {
      id: "actions",
      header: t("colActions"),
      meta: { actions: true },
      cell: ({ row: { original: row } }) => {
        const items: RowAction[] = [];
        const place = placeOf(row);
        if (row.acceptable)
          items.push({
            label: t(withdrawal(row) ? "withdraw" : "accept"),
            icon: <CheckIcon aria-hidden="true" />,
            inline: true,
            main: true,
            onSelect: () => ask("accept", [row]),
          });
        if (place)
          items.push({
            label: t("open"),
            icon: <PencilIcon aria-hidden="true" />,
            // Nothing to accept: reading and translating by hand is the way.
            inline: !row.acceptable,
            main: !row.acceptable,
            link: <Link href={place} />,
          });
        items.push({
          label: t(withdrawal(row) ? "keep" : "discard"),
          icon: <XIcon aria-hidden="true" />,
          destructive: !withdrawal(row),
          separated: true,
          onSelect: () => ask("discard", [row]),
        });
        return (
          <RowActions
            items={items}
            label={t("actionsFor", {
              name: nameOf(row),
              language: nativeName(row.locale),
            })}
          />
        );
      },
    },
  ];

  const first = deciding?.rows[0];
  const single = deciding?.rows.length === 1 ? first : undefined;
  const dialogWords = !deciding
    ? undefined
    : single && withdrawal(single)
      ? deciding.action === "accept"
        ? "withdrawOne"
        : "keepOne"
      : deciding.action === "discard"
        ? "discardOne"
        : single
          ? "acceptOne"
          : "acceptMany";

  return (
    <PanelPage
      actions={
        markable.length > 0 ? (
          <Button
            disabled={marked.length === 0}
            onClick={() => ask("accept", marked)}
            type="button"
          >
            <CheckIcon aria-hidden="true" />
            {t("acceptSelected", { count: marked.length })}
          </Button>
        ) : undefined
      }
      description={t("description")}
      eyebrow={nav("website")}
      notice={notice}
      title={t("title")}
    >
      <TranslationTabs waiting={waiting} />
      {problem || (answer?.problem && !loading) ? (
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
              {t("retry")}
            </Button>
          ) : null}
        </div>
      ) : null}
      <DataTable
        activeFilters={reason ? 1 : 0}
        caption={t("caption")}
        columns={columns}
        data={rows}
        emptyAction={
          reason ? (
            <Button
              onClick={() => setReason("")}
              type="button"
              variant="outline"
            >
              {t("clearFilters")}
            </Button>
          ) : undefined
        }
        filters={
          <DataTableFilter
            id="translation-review-reason"
            label={t("filterReason")}
            onChange={(event) => {
              setSelected(new Set());
              setReason(event.target.value);
            }}
            value={reason}
          >
            <option value="">{t("allReasons")}</option>
            {REASONS.map((item) => (
              <option key={item} value={item}>
                {t(`reasons.${item}`)}
              </option>
            ))}
          </DataTableFilter>
        }
        getRowId={(row) => row.id}
        labels={{ ...labels, empty: reason ? labels.empty : t("empty") }}
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
      <Dialog
        onOpenChange={(open) => {
          if (!open && !busy) setDeciding(undefined);
        }}
        open={deciding !== undefined}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dialogWords
                ? t(`dialog.${dialogWords}.title`, {
                    count: deciding?.rows.length ?? 0,
                  })
                : null}
            </DialogTitle>
            <DialogDescription>
              {dialogWords && first
                ? t(`dialog.${dialogWords}.text`, {
                    name: nameOf(first),
                    language: nativeName(first.locale),
                    count: deciding?.rows.length ?? 0,
                  })
                : null}
            </DialogDescription>
          </DialogHeader>
          {dialogProblem ? (
            <p className="text-sm text-destructive" role="alert">
              {dialogProblem}
            </p>
          ) : null}
          <DialogFooter>
            <Button
              disabled={busy}
              onClick={() => setDeciding(undefined)}
              type="button"
              variant="outline"
            >
              {t("cancel")}
            </Button>
            <Button
              disabled={busy}
              onClick={() => deciding && void decide(deciding)}
              type="button"
              variant={dialogWords === "discardOne" ? "destructive" : "default"}
            >
              {dialogWords ? t(`dialog.${dialogWords}.confirm`) : null}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PanelPage>
  );
}
