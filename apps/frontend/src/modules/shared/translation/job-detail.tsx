"use client";

/** One translation job (TL16d): what it was asked to translate and how each
 *  pair ended, the credits each part held and settled, why it waits — and
 *  the two decisions about it: stopping a job that still runs and taking the
 *  last one back. Both are the server's to refuse; the screen asks first. */

import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { PencilIcon, SquareIcon, Undo2Icon } from "lucide-react";
import {
  ApiProblemError,
  cancelTranslationJob,
  getTranslationJob,
  revertTranslationJob,
  type TranslationJobDetail as Job,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { Progress } from "@saas-core/ui/components/progress";
import { PanelPage } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { nativeName } from "#lib/company-locales";
import { useDataTableLabels } from "#lib/data-table-labels";
import {
  ITEM_TONE,
  JOB_TONE,
  SOURCE_KINDS,
  jobActive,
  jobCredits,
  jobProgress,
  jobWaiting,
  translationPlace,
  useObjectName,
} from "./job-words";

type Item = Job["items"][number];
type Part = Job["parts"][number];
type Outcome = { state?: unknown; reason?: unknown; keys?: unknown };

const POLL_MS = 3000;
const JOBS = "/panel/sites/translations/jobs";

type Asking = {
  action: "cancel" | "revert";
  /** One key per question asked: a repeated click answers the first result. */
  key: string;
};

export function TranslationJobDetail({ jobId }: { jobId: string }) {
  const t = useTranslations("Translations.jobs");
  const review = useTranslations("Translations.review");
  const objectName = useObjectName();
  const format = useFormatter();
  const labels = useDataTableLabels();
  const [answer, setAnswer] = useState<{ job: Job; at: number }>();
  const [loadProblem, setLoadProblem] = useState("");
  const [reloads, setReloads] = useState(0);
  const [asking, setAsking] = useState<Asking>();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [dialogProblem, setDialogProblem] = useState("");

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    // The names are read from the sources once; a job's items do not change.
    let names: Map<string, string> | undefined;
    const ask = () => {
      getTranslationJob(jobId, { labels: names === undefined })
        .then((job) => {
          if (!alive) return;
          names ??= new Map(job.items.map((item) => [item.id, item.label]));
          const known = names;
          setLoadProblem("");
          setAnswer({
            at: Date.now(),
            job: {
              ...job,
              items: job.items.map((item) => ({
                ...item,
                label: known.get(item.id) ?? item.label,
              })),
            },
          });
          if (jobActive(job)) timer = setTimeout(ask, POLL_MS);
        })
        .catch((error: unknown) => {
          if (!alive) return;
          // While following, a failed read is not a failed job: ask again.
          if (names !== undefined) timer = setTimeout(ask, POLL_MS * 2);
          else
            setLoadProblem(
              error instanceof ApiProblemError && error.problem.status === 404
                ? t("detail.notFound")
                : error instanceof ApiProblemError &&
                    error.problem.status === 403
                  ? review("noAccess")
                  : t("loadFailed"),
            );
        });
    };
    ask();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, reloads]);

  const job = answer?.job;
  const when = (value: string) =>
    format.dateTime(new Date(value), {
      dateStyle: "medium",
      timeStyle: "short",
    });

  function open(action: Asking["action"]) {
    setDialogProblem("");
    setAsking({ action, key: crypto.randomUUID() });
  }

  async function decide(asked: Asking) {
    setBusy(true);
    setDialogProblem("");
    setNotice("");
    try {
      await (asked.action === "cancel"
        ? cancelTranslationJob(jobId, asked.key)
        : revertTranslationJob(jobId, asked.key));
      setNotice(
        t(asked.action === "cancel" ? "detail.stopped" : "detail.takenBack"),
      );
      setAsking(undefined);
      setReloads((value) => value + 1);
    } catch (error) {
      const problem =
        error instanceof ApiProblemError ? error.problem : undefined;
      const code = problem?.errors?.[0]?.code;
      if (code === "job_finished" || code === "already_reverted") {
        // It ended, or somebody took it back, meanwhile: show what is.
        setNotice(
          t(
            code === "job_finished"
              ? "detail.finishedMeanwhile"
              : "detail.alreadyReverted",
          ),
        );
        setAsking(undefined);
        setReloads((value) => value + 1);
      } else if (code === "not_latest_job" || code === "job_running") {
        // The server keeps „only the latest, once it ended”: say which.
        setDialogProblem(
          t(
            code === "job_running" ? "detail.stillRunning" : "detail.notLatest",
          ),
        );
        setReloads((value) => value + 1);
      } else
        setDialogProblem(
          problem?.status === 403 ? t("detail.forbidden") : t("detail.failed"),
        );
    } finally {
      setBusy(false);
    }
  }

  if (!job)
    return (
      <PanelPage
        eyebrow={t("tab")}
        eyebrowHref={JOBS}
        title={t("detail.title")}
      >
        {loadProblem ? (
          <div
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
            role="alert"
          >
            <span>{loadProblem}</span>
            <Button
              onClick={() => setReloads((value) => value + 1)}
              size="sm"
              type="button"
              variant="outline"
            >
              {review("retry")}
            </Button>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground" role="status">
            {t("detail.loading")}
          </p>
        )}
      </PanelPage>
    );

  const active = jobActive(job);
  const waiting = jobWaiting(job, answer.at);
  const { done, total } = jobProgress(job);
  const credits = jobCredits(job);
  const kindOf = (item: Item) =>
    review(`kinds.${SOURCE_KINDS[item.source_key] ?? "other"}`);
  const nameOf = (item: Item) => objectName(item) || kindOf(item);
  const word = (group: string, value: string) =>
    t.has(`detail.${group}.${value}`)
      ? t(`detail.${group}.${value}`)
      : t(`detail.${group}.other`);

  const partColumns: ColumnDef<Part, unknown>[] = [
    {
      id: "index",
      accessorFn: (part) => part.index + 1,
      header: t("detail.colPart"),
      meta: { primary: true },
      cell: ({ row: { original: part } }) =>
        t("detail.part", { number: part.index + 1 }),
    },
    {
      id: "state",
      accessorKey: "state",
      header: t("colState"),
      cell: ({ row: { original: part } }) => word("partStates", part.state),
    },
    {
      id: "units",
      accessorKey: "units",
      header: t("detail.colUnits"),
      meta: { numeric: true },
    },
    {
      id: "reserved",
      accessorKey: "reserved_credits",
      header: t("detail.colReserved"),
      meta: { numeric: true },
    },
    {
      id: "settled",
      accessorKey: "settled_credits",
      header: t("detail.colSettled"),
      meta: { numeric: true },
      cell: ({ row: { original: part } }) =>
        part.state === "settled" ? part.settled_credits : "—",
    },
  ];

  const itemColumns: ColumnDef<Item, unknown>[] = [
    {
      id: "what",
      accessorFn: nameOf,
      header: t("detail.colWhat"),
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <>
          <p className="font-medium wrap-anywhere">{nameOf(item)}</p>
          {item.label ? (
            <p className="text-xs text-muted-foreground">{kindOf(item)}</p>
          ) : null}
        </>
      ),
    },
    {
      id: "language",
      accessorFn: (item) => nativeName(item.locale),
      header: t("detail.colLanguage"),
    },
    {
      id: "state",
      accessorKey: "state",
      header: t("colState"),
      meta: { long: true },
      cell: ({ row: { original: item } }) => (
        <div className="space-y-1">
          <Badge variant={ITEM_TONE[item.state] ?? "neutral"}>
            {word("itemStates", item.state)}
          </Badge>
          {(item.outcomes as Outcome[]).map((outcome, index) => (
            <p className="text-xs text-muted-foreground" key={index}>
              {[
                word("outcomes", String(outcome.state)),
                typeof outcome.reason === "string" &&
                review.has(`reasons.${outcome.reason}`)
                  ? review(`reasons.${outcome.reason}`)
                  : "",
              ]
                .filter(Boolean)
                .join(" — ")}
            </p>
          ))}
          {item.error_code && item.state !== "written" ? (
            <p className="text-xs text-muted-foreground">
              {word("errors", item.error_code)}
            </p>
          ) : null}
        </div>
      ),
    },
    {
      id: "characters",
      accessorKey: "delivered_characters",
      header: t("detail.colCharacters"),
      meta: { className: "tabular-nums" },
      cell: ({ row: { original: item } }) =>
        t("detail.characters", {
          delivered: item.delivered_characters,
          quoted: item.quoted_characters,
        }),
    },
    {
      id: "actions",
      header: t("colActions"),
      meta: { actions: true },
      cell: ({ row: { original: item } }) => {
        const place = translationPlace(item);
        return place ? (
          <RowActions
            items={[
              {
                label: review("open"),
                icon: <PencilIcon aria-hidden="true" />,
                inline: true,
                main: true,
                link: <Link href={place} />,
              },
            ]}
            label={review("actionsFor", {
              name: nameOf(item),
              language: nativeName(item.locale),
            })}
          />
        ) : null;
      },
    },
  ];

  return (
    <PanelPage
      actions={
        <>
          {active && job.error_code !== "canceled" ? (
            <Button
              onClick={() => open("cancel")}
              type="button"
              variant="outline"
            >
              <SquareIcon aria-hidden="true" />
              {t("detail.cancel")}
            </Button>
          ) : null}
          {job.revertable ? (
            <Button
              onClick={() => open("revert")}
              type="button"
              variant="outline"
            >
              <Undo2Icon aria-hidden="true" />
              {t("detail.revert")}
            </Button>
          ) : null}
        </>
      }
      eyebrow={t("tab")}
      eyebrowHref={JOBS}
      notice={notice}
      subtitle={t("detail.subtitle", {
        trigger: t(
          `trigger.${job.trigger === "automatic" ? "automatic" : "click"}`,
        ),
        date: when(job.created_at),
      })}
      title={t("detail.title")}
    >
      <section aria-label={t("detail.summary")} className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={JOB_TONE[job.state] ?? "neutral"}>
            {t.has(`states.${job.state}`)
              ? t(`states.${job.state}`)
              : job.state}
          </Badge>
          {job.reverted_at ? (
            <Badge variant="neutral">{t("reverted")}</Badge>
          ) : null}
          <span className="text-sm tabular-nums">
            {t("progress", { done, total })}
          </span>
        </div>
        {active ? (
          <Progress
            aria-label={t("bar.progress", { date: when(job.created_at) })}
            max={Math.max(total, 1)}
            value={done}
          />
        ) : null}
        {waiting ? (
          <p className="text-sm text-muted-foreground">
            {t(`waiting.${waiting}`, { time: when(job.next_attempt_at) })}
          </p>
        ) : null}
        <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
          {(
            [
              ["created", job.created_at],
              ["started", job.started_at],
              ["finished", job.finished_at],
              ["revertedAt", job.reverted_at],
            ] as const
          ).map(([name, value]) =>
            value ? (
              <div key={name}>
                <dt className="text-xs text-muted-foreground">
                  {t(`detail.${name}`)}
                </dt>
                <dd className="tabular-nums">{when(value)}</dd>
              </div>
            ) : null,
          )}
          <div className="sm:col-span-2 lg:col-span-4">
            <dt className="text-xs text-muted-foreground">
              {t("detail.credits")}
            </dt>
            <dd>
              {job.billing === "credits"
                ? t(
                    // The automation pays carried thousands: „wycena 1 ·
                    // rozliczone 0” read like a fault, so it says what it paid.
                    job.trigger === "automatic"
                      ? "detail.creditsLineAutomatic"
                      : "detail.creditsLine",
                    {
                      quoted: job.credits,
                      held: credits.held,
                      settled: credits.settled,
                    },
                  )
                : t("detail.platformBudget")}
              {job.billing === "credits" && job.trigger === "automatic" ? (
                <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
                  {t("detail.carryHint")}
                </p>
              ) : null}
            </dd>
          </div>
        </dl>
      </section>
      <section className="space-y-2">
        <h2 className="text-base font-semibold">{t("detail.items")}</h2>
        <DataTable
          caption={t("detail.items")}
          columns={itemColumns}
          data={job.items}
          getRowId={(item) => item.id}
          labels={labels}
          pageSize={50}
        />
      </section>
      <section className="space-y-2">
        <h2 className="text-base font-semibold">{t("detail.parts")}</h2>
        <p className="text-sm text-muted-foreground">{t("detail.partsHint")}</p>
        <DataTable
          caption={t("detail.parts")}
          columns={partColumns}
          data={job.parts}
          getRowId={(part) => String(part.index)}
          labels={labels}
          pageSize={50}
        />
      </section>
      <Dialog
        onOpenChange={(next) => {
          if (!next && !busy) setAsking(undefined);
        }}
        open={asking !== undefined}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {asking ? t(`detail.${asking.action}Dialog.title`) : null}
            </DialogTitle>
            <DialogDescription>
              {asking ? t(`detail.${asking.action}Dialog.text`) : null}
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
              onClick={() => setAsking(undefined)}
              type="button"
              variant="outline"
            >
              {t("detail.keep")}
            </Button>
            <Button
              disabled={busy}
              onClick={() => asking && void decide(asking)}
              type="button"
            >
              {asking ? t(`detail.${asking.action}Dialog.confirm`) : null}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PanelPage>
  );
}
