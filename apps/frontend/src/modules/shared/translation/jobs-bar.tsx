"use client";

/** The translation jobs still running, above the translations list (TL16d):
 *  how far each has come and, when it stands still, why — with the way to
 *  its detail. Nothing is drawn while nothing runs. A job runs on the
 *  server; this only asks, and stops asking when the last one ends. */

import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  listTranslationJobs,
  type TranslationJob,
} from "@saas-core/api-client";
import { Progress } from "@saas-core/ui/components/progress";
import { Link } from "#i18n/navigation";
import { jobProgress, jobWaiting } from "./job-words";
import { translationComposed } from "./use-translation";

const POLL_MS = 4000;
/** More than these run only in a burst; the „Zadania” tab lists them all. */
const SHOWN = 5;

export function TranslationJobsBar({
  reloadKey = "",
  onFinished,
}: {
  /** Changes when a job may have started: the bar asks again. */
  reloadKey?: string | number;
  /** A job the bar was following has ended: what it wrote is in place. */
  onFinished?: () => void;
}) {
  const t = useTranslations("Translations.jobs");
  const format = useFormatter();
  const [answer, setAnswer] = useState<{
    jobs: TranslationJob[];
    at: number;
  }>();

  useEffect(() => {
    // No engine in this deployment: no jobs to ask about.
    if (!translationComposed()) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let followed = new Set<string>();
    const ask = () => {
      listTranslationJobs({ active: true, limit: SHOWN })
        .then((page) => {
          if (!alive) return;
          const running = new Set(page.items.map((job) => job.id));
          const ended = [...followed].some((id) => !running.has(id));
          followed = running;
          setAnswer({ jobs: page.items, at: Date.now() });
          if (ended) onFinished?.();
          if (running.size > 0) timer = setTimeout(ask, POLL_MS);
        })
        .catch(() => {
          // No engine here, or not this person's to see: no bar. While a job
          // is followed, a failed read is not a failed job: ask again.
          if (alive && followed.size > 0) timer = setTimeout(ask, POLL_MS * 2);
        });
    };
    ask();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
    // `onFinished` is the same for the list's life.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadKey]);

  if (!answer || answer.jobs.length === 0) return null;
  const when = (value: string) =>
    format.dateTime(new Date(value), {
      dateStyle: "medium",
      timeStyle: "short",
    });
  return (
    <section aria-label={t("bar.label")}>
      <ul className="space-y-2">
        {answer.jobs.map((job) => {
          const { done, total } = jobProgress(job);
          const waiting = jobWaiting(job, answer.at);
          const created = when(job.created_at);
          return (
            <li
              className="space-y-2 rounded-lg border border-border p-3 text-sm"
              key={job.id}
            >
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <p>
                  <span className="font-medium">
                    {t(job.state === "queued" ? "bar.queued" : "bar.running", {
                      done,
                      total,
                    })}
                  </span>{" "}
                  <span className="text-muted-foreground">
                    {t(
                      `bar.from.${job.trigger === "automatic" ? "automatic" : "click"}`,
                      {
                        date: created,
                      },
                    )}
                  </span>
                </p>
                <Link
                  aria-label={t("detailsOf", { date: created })}
                  className="font-medium text-primary underline-offset-2 hover:underline"
                  href={`/panel/sites/translations/jobs/${job.id}`}
                >
                  {t("details")}
                </Link>
              </div>
              <Progress
                aria-label={t("bar.progress", { date: created })}
                max={Math.max(total, 1)}
                value={done}
              />
              {waiting ? (
                <p className="text-muted-foreground">
                  {t(`waiting.${waiting}`, {
                    time: when(job.next_attempt_at),
                  })}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
