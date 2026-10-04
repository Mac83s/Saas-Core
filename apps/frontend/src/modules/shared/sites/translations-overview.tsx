"use client";

/** „Strona internetowa → Tłumaczenia” (TL16): every page or article of the
 *  site — and the site's own texts, the company's card and its services —
 *  against the site's other languages: what is translated, what waits and
 *  what is missing, with the way into each language version, its preview,
 *  its place on the site, the decision on what waits and the order for an
 *  automatic translation. The list is the server's: its filters and its
 *  pages are asked for, never computed here. */

import { useEffect, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  CheckIcon,
  ExternalLinkIcon,
  EyeIcon,
  LanguagesIcon,
  NewspaperIcon,
  PencilIcon,
} from "lucide-react";
import {
  ApiProblemError,
  decideTranslationReview,
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { Link } from "#i18n/navigation";
import { nativeName } from "#lib/company-locales";
import { useDataTableLabels } from "#lib/data-table-labels";
import { SOURCE_KINDS, translationPlace } from "../translation/job-words";
import { TranslationJobsBar } from "../translation/jobs-bar";
import { ReviewCompareDialog } from "../translation/review-compare";
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
import { SiteTextsSheet } from "./site-texts-sheet";

type Row = TranslationOverview["items"][number];
type Cell = Row["cells"][number];
type Kind = Row["kind"];
type CellState = Cell["state"];

const PAGE_SIZE = 50;

/** The states a filter offers, per kind, in the order work goes. */
const STATES: Record<Kind, readonly CellState[]> = {
  page: ["missing", "pending", "outdated", "untranslated", "complete"],
  entry: ["missing", "draft", "published"],
  other: ["missing", "pending", "outdated", "untranslated", "complete"],
};

const KINDS = ["page", "entry", "other"] as const satisfies readonly Kind[];

/** The site's own texts have no page of their own: they open in a sheet. */
const SITE_TEXTS = "sites.site_texts";

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

/** The row's languages still to translate, as an order names them: a page
 *  or another source's object by itself, an article by its entry in the
 *  site's own language — an article without one cannot be ordered. An
 *  article's version that exists is a person's to finish, so only the
 *  missing ones are ordered. */
function rowTargets(row: Row): TranslationTarget[] {
  const source = row.source_id;
  if (!source) return [];
  return row.cells
    .filter((cell) =>
      row.kind === "entry"
        ? cell.state === "missing"
        : NEEDS_TRANSLATION.has(cell.state),
    )
    .map((cell) => ({
      source_key: row.source_key,
      object_id: source,
      locale: cell.locale,
      basis: "published" as const,
    }));
}

/** Everything of the site — pages, articles, its own texts, the card and
 *  the services — that has a language to translate. */
async function siteTargets(siteId: string): Promise<TranslationTarget[]> {
  const targets: TranslationTarget[] = [];
  for (const kind of KINDS) {
    let cursor: string | null = null;
    do {
      const answer: TranslationOverview = await getSiteTranslationOverview(
        siteId,
        { kind, limit: 100, ...(cursor ? { cursor } : {}) },
      );
      targets.push(...answer.items.flatMap(rowTargets));
      cursor = answer.next_cursor;
    } while (cursor);
  }
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
  onOrdered,
  onDone,
}: {
  siteId: string;
  /** An order was placed: a job runs now. */
  onOrdered?: () => void;
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
        onOrdered={(started) => {
          setJobId(started.id);
          onOrdered?.();
        }}
        open={targets !== undefined}
        reasonText={reasonText}
        targets={targets ?? []}
      />
    </>
  );
}

const CELL_ACTION =
  "inline-flex items-center gap-1 text-xs font-medium text-primary underline-offset-2 hover:underline";

/** One language of a row: its state and what can be done with it right
 *  there — edit, preview, open on the site, accept what waits. */
function CellBadge({
  cell,
  name,
  edit,
  previewHref,
  publicHref,
  onAccept,
}: {
  cell: Cell;
  /** What the row is called, for the names of its actions. */
  name: string;
  /** The way into this language's editor: an address, or a sheet to open. */
  edit?: { href: string } | { open: () => void };
  previewHref?: string;
  publicHref?: string;
  /** A result waits here and this person can accept it. */
  onAccept?: () => void;
}) {
  const t = useTranslations("Sites.translationsCentre");
  const language = nativeName(cell.locale);
  const actions: ReactNode[] = [];
  if (edit && "href" in edit)
    actions.push(
      <Link
        aria-label={t("editIn", { language })}
        className={CELL_ACTION}
        href={edit.href}
        key="edit"
      >
        <PencilIcon aria-hidden="true" className="size-3" />
        {t("edit")}
      </Link>,
    );
  else if (edit)
    actions.push(
      <button
        aria-label={t("editIn", { language })}
        className={CELL_ACTION}
        key="edit"
        onClick={edit.open}
        type="button"
      >
        <PencilIcon aria-hidden="true" className="size-3" />
        {t("edit")}
      </button>,
    );
  if (previewHref)
    actions.push(
      <Link
        aria-label={t("previewOf", { name, language })}
        className={CELL_ACTION}
        href={previewHref}
        key="preview"
      >
        <EyeIcon aria-hidden="true" className="size-3" />
        {t("preview")}
      </Link>,
    );
  if (publicHref)
    actions.push(
      <a
        aria-label={t("openPublicOf", { name, language })}
        className={CELL_ACTION}
        href={publicHref}
        key="public"
        rel="noreferrer"
        target="_blank"
      >
        <ExternalLinkIcon aria-hidden="true" className="size-3" />
        {t("openPublic")}
      </a>,
    );
  if (onAccept)
    actions.push(
      <button
        aria-label={t("acceptOf", { name, language })}
        className={CELL_ACTION}
        key="accept"
        onClick={onAccept}
        type="button"
      >
        <CheckIcon aria-hidden="true" className="size-3" />
        {t("accept")}
      </button>,
    );
  return (
    <div className="space-y-1">
      <Badge variant={TONE[cell.state]}>{t(`states.${cell.state}`)}</Badge>
      {actions.length ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {actions}
        </div>
      ) : null}
      {cell.state === "untranslated" && cell.untranslated ? (
        <p className="text-xs text-muted-foreground">
          {t("untranslatedCount", { count: cell.untranslated })}
        </p>
      ) : null}
      {cell.state !== "missing" && cell.metadata_complete === false ? (
        <p className="text-xs text-muted-foreground">{t("noMetadata")}</p>
      ) : null}
      {/* „Przetłumaczona” is not yet „na stronie”: a publication puts it there. */}
      {cell.state !== "missing" && typeof cell.on_site === "boolean" ? (
        <p className="text-xs text-muted-foreground">
          {t(cell.on_site ? "onSite" : "notOnSite")}
        </p>
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

/** A result waiting in a cell, as the review queue names it. */
type Waiting = {
  row: Row;
  locale: string;
  id: string;
  version: number;
  /** Its text is read beside the source before the decision. */
  comparable: boolean;
  /** One key per decision asked: a repeated click answers the first result. */
  key: string;
};

export function TranslationsOverview({
  siteId,
  reloadKey = 0,
  publicBaseUrl,
  onDecided,
}: {
  siteId: string;
  /** Changes when something outside the list changed what it shows. */
  reloadKey?: number;
  /** The published site's address, when it has one. */
  publicBaseUrl?: string | null;
  /** A waiting result was accepted here: less waits in „Do akceptacji”. */
  onDecided?: () => void;
}) {
  const t = useTranslations("Sites.translationsCentre");
  const sites = useTranslations("Sites");
  const review = useTranslations("Translations.review");
  const skipped = useTranslations("Sites.languageMode.skipped");
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
  // The site's own texts in one language, open in their sheet.
  const [textsLocale, setTextsLocale] = useState<string>();
  const [accepting, setAccepting] = useState<Waiting>();
  const [deciding, setDeciding] = useState(false);
  const [decisionProblem, setDecisionProblem] = useState("");
  const [notice, setNotice] = useState("");
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

  const kindOf = (row: Row) =>
    review(`kinds.${SOURCE_KINDS[row.source_key] ?? "other"}`);

  function askToAccept(row: Row, cell: Cell) {
    if (!cell.review_id || cell.review_version == null) return;
    setDecisionProblem("");
    setNotice("");
    setAccepting({
      row,
      locale: cell.locale,
      id: cell.review_id,
      version: cell.review_version,
      comparable: cell.review_comparable === true,
      key: crypto.randomUUID(),
    });
  }

  /** Somebody decided it meanwhile, or a newer result replaced it. */
  function gone() {
    setAccepting(undefined);
    setNotice(review("changed"));
    setReloads((value) => value + 1);
    onDecided?.();
  }

  async function accept(waiting: Waiting, version: number) {
    setDeciding(true);
    setDecisionProblem("");
    try {
      const result = await decideTranslationReview(
        "accept",
        [{ id: waiting.id, version }],
        waiting.key,
      );
      // Accepted, but its source could not put it out yet — with the reason.
      const held = result.items
        .flatMap((item) => item.outcomes)
        .find((outcome) => outcome.state === "pending");
      const why = typeof held?.reason === "string" ? held.reason : "other";
      setNotice(
        held
          ? review("acceptedNotPublished", {
              count: 1,
              reason: skipped.has(why) ? skipped(why) : skipped("other"),
            })
          : review("accepted", { count: 1 }),
      );
      setAccepting(undefined);
      setReloads((value) => value + 1);
      onDecided?.();
    } catch (error) {
      const problem =
        error instanceof ApiProblemError ? error.problem : undefined;
      if (problem?.code === "translation_review_changed") gone();
      else
        setDecisionProblem(
          review(problem?.status === 403 ? "forbidden" : "failed"),
        );
    } finally {
      setDeciding(false);
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
      header: t(
        kind === "page"
          ? "colPage"
          : kind === "entry"
            ? "colEntry"
            : "colOther",
      ),
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <>
          <p className="font-medium wrap-anywhere">{row.title}</p>
          {/* A card and a catalogue carry the company's name: say which is which. */}
          {row.kind === "other" ? (
            <p className="text-xs text-muted-foreground">{kindOf(row)}</p>
          ) : null}
        </>
      ),
    },
    ...shown.map((code): ColumnDef<Row, unknown> => ({
      id: `language-${code}`,
      accessorFn: (row) =>
        row.cells.find((cell) => cell.locale === code)?.state ?? "",
      header: nativeName(code),
      cell: ({ row: { original: row } }) => {
        const cell = row.cells.find((item) => item.locale === code);
        if (!cell) return "—";
        const editor = `/panel/sites/pages/${row.id}?language=${code}`;
        // Several languages: each one's editor is in its own column, in sight.
        const edit =
          shown.length <= 1
            ? undefined
            : row.kind === "page"
              ? { href: editor }
              : row.source_key === SITE_TEXTS
                ? { open: () => setTextsLocale(code) }
                : undefined;
        return (
          <CellBadge
            cell={cell}
            edit={edit}
            name={row.title}
            onAccept={cell.review_id ? () => askToAccept(row, cell) : undefined}
            // A version that exists is read as visitors would get it.
            previewHref={
              row.kind === "page" && cell.state !== "missing"
                ? `${editor}&preview=1`
                : undefined
            }
            publicHref={
              publicBaseUrl && cell.path
                ? `${publicBaseUrl}${cell.path}`
                : undefined
            }
          />
        );
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
        } else if (row.kind === "entry") {
          items.push({
            label: t("openBlog"),
            icon: <NewspaperIcon aria-hidden="true" />,
            inline: true,
            main: true,
            link: <Link href={`/panel/sites/blog?site=${siteId}`} />,
          });
        } else if (row.source_key === SITE_TEXTS) {
          const only = shown.length === 1;
          for (const code of shown)
            if (row.cells.some((cell) => cell.locale === code))
              items.push({
                label: t("editIn", { language: nativeName(code) }),
                icon: <PencilIcon aria-hidden="true" />,
                inline: only,
                main: only,
                onSelect: () => setTextsLocale(code),
              });
        } else {
          // A card and the services are translated where they are edited.
          const place = translationPlace({
            source_key: row.source_key,
            object_id: row.id,
            locale: "",
            scope: "",
          });
          if (place)
            items.push({
              label: t("edit"),
              icon: <PencilIcon aria-hidden="true" />,
              inline: true,
              main: true,
              link: <Link href={place} />,
            });
        }
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
      {offer.state === "absent" || offer.state === "loading" ? null : (
        <TranslationJobsBar
          onFinished={() => setReloads((value) => value + 1)}
          // Asked again when an order is placed here or from the page's header.
          reloadKey={`${reloadKey}|${jobId ?? ""}`}
        />
      )}
      <p className="text-sm text-muted-foreground empty:hidden" role="status">
        {notice}
      </p>
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
        // Rows of the previous query never stand under the new one's columns.
        data={loading ? [] : rows}
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
              <option value="other">{t("kindOther")}</option>
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
            : t(
                kind === "page"
                  ? "emptyPages"
                  : kind === "entry"
                    ? "emptyEntries"
                    : "emptyOther",
              ),
        }}
        loading={loading}
        pageSize={PAGE_SIZE}
      />
      {kind === "entry" ? (
        <p className="text-sm text-muted-foreground">{t("entryHint")}</p>
      ) : null}
      {kind === "other" ? (
        <p className="text-sm text-muted-foreground">{t("otherHint")}</p>
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
      <SiteTextsSheet
        locale={textsLocale}
        onChanged={() => setReloads((value) => value + 1)}
        onClose={() => setTextsLocale(undefined)}
        siteId={siteId}
      />
      {/* A page's or the site's waiting text is read in its own editor: here
          the decision only needs saying once more. */}
      <Dialog
        onOpenChange={(open) => {
          if (!open && !deciding) setAccepting(undefined);
        }}
        open={accepting !== undefined && !accepting.comparable}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {review("dialog.acceptOne.title", { count: 1 })}
            </DialogTitle>
            <DialogDescription>
              {accepting
                ? review("dialog.acceptOne.text", {
                    name: accepting.row.title,
                    language: nativeName(accepting.locale),
                    count: 1,
                  })
                : null}
            </DialogDescription>
          </DialogHeader>
          {decisionProblem ? (
            <p className="text-sm text-destructive" role="alert">
              {decisionProblem}
            </p>
          ) : null}
          <DialogFooter>
            <Button
              disabled={deciding}
              onClick={() => setAccepting(undefined)}
              type="button"
              variant="outline"
            >
              {review("cancel")}
            </Button>
            <Button
              disabled={deciding}
              onClick={() =>
                accepting && void accept(accepting, accepting.version)
              }
              type="button"
            >
              {review("dialog.acceptOne.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {/* A card's or the catalogue's waiting text exists only in the queue:
          it is read beside its source first, and accepted at that version. */}
      <ReviewCompareDialog
        busy={deciding}
        name={accepting?.row.title ?? ""}
        onAccept={(detail) =>
          accepting && void accept(accepting, detail.version)
        }
        onClose={() => setAccepting(undefined)}
        onGone={gone}
        problem={decisionProblem}
        reason={accepting ? kindOf(accepting.row) : ""}
        row={
          accepting?.comparable
            ? { id: accepting.id, locale: accepting.locale }
            : undefined
        }
      />
    </div>
  );
}
