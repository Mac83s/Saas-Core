import type { TranslationJob } from "@saas-core/api-client";

/** What the panel reads off a translation job (TL16d): whether it still
 *  runs, how far it has come and why it stands still. */

type Tone = "neutral" | "info" | "success" | "warning" | "destructive";

export const JOB_TONE: Record<string, Tone> = {
  queued: "neutral",
  running: "info",
  succeeded: "success",
  partial: "warning",
  failed: "destructive",
  canceled: "neutral",
};

export const ITEM_TONE: Record<string, Tone> = {
  queued: "neutral",
  running: "info",
  written: "success",
  failed: "destructive",
  canceled: "neutral",
};

const ACTIVE = new Set(["queued", "running"]);
const ITEM_ENDED = new Set(["written", "failed", "canceled"]);

export const jobActive = (job: Pick<TranslationJob, "state">) =>
  ACTIVE.has(job.state);

/** Pairs (object × language) that ended, of all the job has. */
export function jobProgress(job: Pick<TranslationJob, "items">) {
  return {
    done: job.items.filter((item) => ITEM_ENDED.has(item.state)).length,
    total: job.items.length,
  };
}

/** A wait shorter than this is the worker's own pace, not a reason. */
const WAIT_WORTH_SAYING_MS = 30_000;

/** Why a job that has not ended is not moving at `now`. */
export function jobWaiting(
  job: Pick<
    TranslationJob,
    "state" | "error_code" | "confirmation_required" | "next_attempt_at"
  >,
  now: number,
): "stopping" | "confirmation" | "pool" | undefined {
  if (!jobActive(job)) return undefined;
  if (job.error_code === "canceled") return "stopping";
  if (job.confirmation_required) return "confirmation";
  return new Date(job.next_attempt_at).getTime() - now > WAIT_WORTH_SAYING_MS
    ? "pool"
    : undefined;
}

/** Credits the job's parts hold now and those already settled. */
export function jobCredits(job: Pick<TranslationJob, "parts">) {
  let held = 0;
  let settled = 0;
  for (const part of job.parts) {
    if (part.state === "settled") settled += part.settled_credits;
    else held += part.reserved_credits;
  }
  return { held, settled };
}

/** What each source's object is called in the panel. */
export const SOURCE_KINDS: Record<string, string> = {
  "sites.page": "page",
  "sites.entry": "entry",
  "sites.site_texts": "siteTexts",
  "profiles.public_profile": "profile",
  "booking.catalog": "catalog",
};

/** Where a translated object's text can be read and changed by hand. */
export function translationPlace(of: {
  source_key: string;
  object_id: string;
  locale: string;
  scope: string;
}): string | undefined {
  switch (of.source_key) {
    case "sites.page":
      return `/panel/sites/pages/${of.object_id}?language=${of.locale}`;
    case "sites.entry":
      return of.scope
        ? `/panel/sites/blog?site=${of.scope}`
        : "/panel/sites/blog";
    case "profiles.public_profile":
      return "/panel/profile";
    case "booking.catalog":
      return "/panel/settings/services";
    default:
      return undefined;
  }
}
