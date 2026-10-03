"use client";

/** „Strona internetowa → Tłumaczenia” (TL16): every page or article of the
 *  site against the site's other languages — what is translated, what waits
 *  and what is missing — with the way into each language version and the
 *  order for an automatic translation. The list is the server's: its filters
 *  and its pages are asked for, never computed here. */

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { LanguagesIcon, NewspaperIcon, PencilIcon } from "lucide-react";
import {
  getSiteTranslationOverview,
  type TranslationOverview,
  type TranslationOverviewQuery,
  type TranslationTarget,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  DataTableFilter,
  RowActions,
  type ColumnDef,
  type RowAction,
} from "@saas-core/ui/components/data-table";
import { Link } from "#i18n/navigation";
import { nativeName } from "#lib/company-locales";
import { useDataTableLabels } from "#lib/data-table-labels";
import {
  TranslateDialog,
  TranslationUnavailable,
} from "../translation/translate-dialog";
import {
  translationJobFinished,
  useTranslationJob,
  useTranslationOffer,
} from "../translation/use-translation";
import { sitesErrorMessage } from "./problem";

type Row = TranslationOverview["items"][number];
type Cell = Row["cells"][number];
type Kind = Row["kind"];
type CellState = Cell["state"];

const PAGE_SIZE = 50;

/** The states a filter offers, per kind, in the order work goes. */
const STATES: Record<Kind, readonly CellState[]> = {
  page: ["missing", "pending", "outdated", "untranslated", "complete"],
  entry: ["missing", "draft", "published"],
};

const TONE: Record<CellState, "neutral" | "warning" | "success"> = {
  missing: "neutral",
  pending: "warning",
  outdated: "warning",
  untranslated: "warning",
  complete: "success",
  published: "success",
  draft: "neutral",
};

/** What an automatic translation would fill in. A version waiting for a
 *  person's decision is theirs to decide first. */
const NEEDS_TRANSLATION = new Set<CellState>([
  "missing",
  "outdated",
  "untranslated",
]);

/** A page's languages still to translate. An article is named here by its
 *  group, not by the entry an order needs, so articles are ordered from
 *  their own card in the blog. */
function rowTargets(row: Row): TranslationTarget[] {
  if (row.kind !== "page") return [];
  return row.cells
    .filter((cell) => NEEDS_TRANSLATION.has(cell.state))
    .map((cell) => ({
      source_key: "sites.page",
      object_id: row.id,
      locale: cell.locale,
      basis: "published" as const,
    }));
}

/** Every page of the site that has a language to translate. */
async function siteTargets(siteId: string): Promise<TranslationTarget[]> {
  const targets: TranslationTarget[] = [];
  let cursor: string | null = null;
  do {
    const answer: TranslationOverview = await getSiteTranslationOverview(
      siteId,
      { kind: "page", limit: 100, ...(cursor ? { cursor } : {}) },
    );
    targets.push(...answer.items.flatMap(rowTargets));
    cursor = answer.next_cursor;
  } while (cursor);
  return targets;
}

function useReasonText() {
  const t = useTranslations("Sites.languageMode.banner.reasons");
  return (reason: string) => (t.has(reason) ? t(reason) : t("other"));
}

/** The page's own action: „Przetłumacz brakujące i nieaktualne”. Shown only
 *  where an order can be taken; the list below says why when it cannot. */
export function TranslateSiteAction({
  siteId,
  onDone,
}: {
  siteId: string;
  /** The order ended: what the list shows has changed. */
  onDone: () => void;
}) {
  const t = useTranslations("Sites");
  const reasonText = useReasonText();
  const offer = useTranslationOffer();
  const [targets, setTargets] = useState<TranslationTarget[]>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [jobId, setJobId] = useState<string>();
  const job = useTranslationJob(jobId);
  const jobDone = translationJobFinished(job);
  useEffect(() => {
    if (jobDone) onDone();
    // `onDone` is the same for the page's life.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobDone]);

  if (offer.state !== "available") return null;

  async function ask() {
    setBusy(true);
    setMessage("");
    try {
      const found = await siteTargets(siteId);
      if (found.length === 0) {
        setMessage(t("translationsCentre.nothingToTranslate"));
        return;
      }
      // An order that ended is history: quote anew.
      if (jobDone) setJobId(undefined);
      setTargets(found);
    } catch (error) {
      setMessage(sitesErrorMessage(error, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="text-sm text-muted-foreground empty:hidden" role="status">
        {message}
      </p>
      <Button disabled={busy} onClick={() => void ask()} type="button">
        <LanguagesIcon aria-hidden="true" />
        {t("translationsCentre.translateAll")}
      </Button>
      <TranslateDialog
        job={job}
        languageName={nativeName}
        offer={offer.offer}
        onOpenChange={(open) => {
          if (!open) setTargets(undefined);
        }}
        onOrdered={(started) => setJobId(started.id)}
        open={targets !== undefined}
        reasonText={reasonText}
        targets={targets ?? []}
      />
    </>
  );
}

function CellBadge({ cell }: { cell: Cell }) {
  const t = useTranslations("Sites.translationsCentre");
  return (
    <div className="space-y-1">
      <Badge variant={TONE[cell.state]}>{t(`states.${cell.state}`)}</Badge>
      {cell.state === "untranslated" && cell.untranslated ? (
        <p className="text-xs text-muted-foreground">
          {t("untranslatedCount", { count: cell.untranslated })}
        </p>
      ) : null}
      {cell.state !== "missing" && cell.metadata_complete === false ? (
        <p className="text-xs text-muted-foreground">{t("noMetadata")}</p>
      ) : null}
    </div>
  );
}

type Answer = {
  /** The query this answers; another one is still loading. */
  key: string;
  rows: Row[];
  locales: string[];
  cursor: string | null;
  problem?: string;
};

export function TranslationsOverview({
  siteId,
  reloadKey = 0,
}: {
  siteId: string;
  /** Changes when something outside the list changed what it shows. */
  reloadKey?: number;
}) {
  const t = useTranslations("Sites.translationsCentre");
  const sites = useTranslations("Sites");
  const reasonText = useReasonText();
  const labels = useDataTableLabels();
  const offer = useTranslationOffer();
  const [kind, setKind] = useState<Kind>("page");
  const [locale, setLocale] = useState("");
  const [state, setState] = useState<CellState | "">("");
  const [answer, setAnswer] = useState<Answer>();
  // The site's other languages, as the unfiltered list names them: a list
  // narrowed to one language answers with that one only.
  const [siteLocales, setSiteLocales] = useState<string[]>();
  const [reloads, setReloads] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [translating, setTranslating] = useState<Row>();
  const [jobId, setJobId] = useState<string>();
  const job = useTranslationJob(jobId);
  const jobDone = translationJobFinished(job);

  // Again when an order ends: it wrote the versions listed here.
  const key = [siteId, kind, locale, state, reloads, reloadKey, jobDone].join(
    "|",
  );
  const query = (cursor?: string): TranslationOverviewQuery => ({
    kind,
    limit: PAGE_SIZE,
    ...(locale ? { locale } : {}),
    ...(state ? { state } : {}),
    ...(cursor ? { cursor } : {}),
  });

  useEffect(() => {
    let alive = true;
    getSiteTranslationOverview(siteId, query())
      .then((result) => {
        if (!alive) return;
        setAnswer({
          key,
          rows: result.items,
          locales: result.locales,
          cursor: result.next_cursor,
        });
        if (!locale) setSiteLocales(result.locales);
      })
      .catch((error: unknown) => {
        if (alive)
          setAnswer({
            key,
            rows: [],
            locales: [],
            cursor: null,
            problem: sitesErrorMessage(error, sites),
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
  const shown = answer?.locales ?? [];
  const activeFilters =
    (kind !== "page" ? 1 : 0) + (locale ? 1 : 0) + (state ? 1 : 0);

  async function loadMore(cursor: string) {
    setLoadingMore(true);
    try {
      const more = await getSiteTranslationOverview(siteId, query(cursor));
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
      setAnswer((current) =>
        current?.key === key
          ? { ...current, problem: sitesErrorMessage(error, sites) }
          : current,
      );
    } finally {
      setLoadingMore(false);
    }
  }

  if (siteLocales?.length === 0 && !answer?.problem) {
    return (
      <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
        {t("oneLanguage")}{" "}
        <Link
          className="font-medium text-primary underline"
          href="/panel/settings/languages"
        >
          {t("addLanguage")}
        </Link>
      </p>
    );
  }

  const columns: ColumnDef<Row, unknown>[] = [
    {
      id: "title",
      accessorKey: "title",
      header: t(kind === "page" ? "colPage" : "colEntry"),
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <p className="font-medium wrap-anywhere">{row.title}</p>
      ),
    },
    ...shown.map((code): ColumnDef<Row, unknown> => ({
      id: `language-${code}`,
      accessorFn: (row) =>
        row.cells.find((cell) => cell.locale === code)?.state ?? "",
      header: nativeName(code),
      cell: ({ row: { original: row } }) => {
        const cell = row.cells.find((item) => item.locale === code);
        return cell ? <CellBadge cell={cell} /> : "—";
      },
    })),
    {
      id: "actions",
      header: t("colActions"),
      meta: { actions: true },
      cell: ({ row: { original: row } }) => {
        const items: RowAction[] = [];
        if (row.kind === "page") {
          // One other language: its editor is the row's „Edytuj”, in sight.
          const only = shown.length === 1;
          for (const code of shown)
            items.push({
              label: t("editIn", { language: nativeName(code) }),
              icon: <PencilIcon aria-hidden="true" />,
              inline: only,
              main: only,
              link: (
                <Link href={`/panel/sites/pages/${row.id}?language=${code}`} />
              ),
            });
          if (offer.state === "available" && rowTargets(row).length > 0)
            items.push({
              label: sites("languageMode.actions.translate"),
              icon: <LanguagesIcon aria-hidden="true" />,
              onSelect: () => {
                // An order that ended is history: quote anew.
                if (jobDone) setJobId(undefined);
                setTranslating(row);
              },
            });
        } else {
          items.push({
            label: t("openBlog"),
            icon: <NewspaperIcon aria-hidden="true" />,
            inline: true,
            main: true,
            link: <Link href={`/panel/sites/blog?site=${siteId}`} />,
          });
        }
        return (
          <RowActions
            items={items}
            label={t("actionsFor", { name: row.title })}
          />
        );
      },
    },
  ];

  return (
    <div className="space-y-4">
      {offer.state === "unavailable" ? (
        <TranslationUnavailable reasons={offer.reasons} />
      ) : null}
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
            {t("retry")}
          </Button>
        </div>
      ) : null}
      <DataTable
        activeFilters={activeFilters}
        caption={t("caption")}
        columns={columns}
        data={rows}
        emptyAction={
          activeFilters ? (
            <Button
              onClick={() => {
                setKind("page");
                setLocale("");
                setState("");
              }}
              type="button"
              variant="outline"
            >
              {t("clearFilters")}
            </Button>
          ) : undefined
        }
        filters={
          <>
            <DataTableFilter
              id="translations-kind"
              label={t("filterKind")}
              onChange={(event) => {
                setKind(event.target.value as Kind);
                // The states are the kind's own.
                setState("");
              }}
              value={kind}
            >
              <option value="page">{t("kindPage")}</option>
              <option value="entry">{t("kindEntry")}</option>
            </DataTableFilter>
            {(siteLocales?.length ?? 0) > 1 ? (
              <DataTableFilter
                id="translations-language"
                label={t("filterLanguage")}
                onChange={(event) => setLocale(event.target.value)}
                value={locale}
              >
                <option value="">{t("allLanguages")}</option>
                {siteLocales?.map((code) => (
                  <option key={code} value={code}>
                    {nativeName(code)}
                  </option>
                ))}
              </DataTableFilter>
            ) : null}
            <DataTableFilter
              id="translations-state"
              label={t("filterState")}
              onChange={(event) =>
                setState(event.target.value as CellState | "")
              }
              value={state}
            >
              <option value="">{t("allStates")}</option>
              {STATES[kind].map((item) => (
                <option key={item} value={item}>
                  {t(`states.${item}`)}
                </option>
              ))}
            </DataTableFilter>
          </>
        }
        getRowId={(row) => row.id}
        labels={{
          ...labels,
          empty: activeFilters
            ? labels.empty
            : t(kind === "page" ? "emptyPages" : "emptyEntries"),
        }}
        loading={loading}
        pageSize={PAGE_SIZE}
      />
      {kind === "entry" ? (
        <p className="text-sm text-muted-foreground">{t("entryHint")}</p>
      ) : null}
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
      {offer.state === "available" ? (
        <TranslateDialog
          job={job}
          languageName={nativeName}
          offer={offer.offer}
          onOpenChange={(open) => {
            if (!open) setTranslating(undefined);
          }}
          onOrdered={(started) => setJobId(started.id)}
          open={translating !== undefined}
          reasonText={reasonText}
          targets={translating ? rowTargets(translating) : []}
        />
      ) : null}
    </div>
  );
}
