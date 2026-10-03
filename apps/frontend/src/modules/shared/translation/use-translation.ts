"use client";

import { useEffect, useState } from "react";

import {
  getTranslationJob,
  getTranslationOffer,
  type TranslationJob,
  type TranslationOffer,
} from "@saas-core/api-client";

/** Whether automatic translation can be ordered here:
 *  - `absent`: the deployment has no translation engine — nothing is said;
 *  - `unavailable`: the engine is there but cannot take an order now, with
 *    the reasons, so a screen can say why in the customer's words;
 *  - `available`: orders are taken. */
export type TranslationOfferState =
  | { state: "loading" }
  | { state: "absent" }
  | { state: "unavailable"; reasons: readonly string[]; offer: TranslationOffer }
  | { state: "available"; offer: TranslationOffer };

export function useTranslationOffer(): TranslationOfferState {
  const [offer, setOffer] = useState<TranslationOfferState>({ state: "loading" });
  useEffect(() => {
    let alive = true;
    getTranslationOffer()
      .then((answer) => {
        if (!alive) return;
        setOffer(
          answer.available
            ? { state: "available", offer: answer }
            : { state: "unavailable", reasons: answer.reasons, offer: answer },
        );
      })
      .catch(() => {
        if (alive) setOffer({ state: "absent" });
      });
    return () => {
      alive = false;
    };
  }, []);
  return offer;
}

const TERMINAL = new Set(["succeeded", "partial", "failed", "canceled"]);

export function translationJobFinished(job: TranslationJob | undefined): boolean {
  return job !== undefined && TERMINAL.has(job.state);
}

/** Follows one order until it ends. The job runs on the server, so leaving
 *  the screen — or closing the dialog that ordered it — does not stop it;
 *  this only stops asking. */
export function useTranslationJob(
  jobId: string | undefined,
  intervalMs = 2500,
): TranslationJob | undefined {
  const [job, setJob] = useState<TranslationJob>();
  useEffect(() => {
    if (!jobId) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ask = () => {
      getTranslationJob(jobId)
        .then((answer) => {
          if (!alive) return;
          setJob(answer);
          if (!TERMINAL.has(answer.state)) timer = setTimeout(ask, intervalMs);
        })
        .catch(() => {
          // A failed read is not a failed job: ask again.
          if (alive) timer = setTimeout(ask, intervalMs * 2);
        });
    };
    ask();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, intervalMs]);
  return jobId && job?.id === jobId ? job : undefined;
}
