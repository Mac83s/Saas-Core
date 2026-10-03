"use client";

/** „Przetłumacz” (TL15): one dialog for every screen that orders an
 *  automatic translation — the caller names what to translate, the dialog
 *  says how much it is, what it costs against what the company has, where
 *  the result lands, and orders it on the person's click. The job runs on
 *  the server: closing the dialog does not stop it, and the caller follows
 *  it (`useTranslationJob`) to refresh its own screen when it ends. */

import {
  ApiProblemError,
  getCustomerCredits,
  orderTranslation,
  quoteTranslation,
  type TranslationJob,
  type TranslationOffer,
  type TranslationProtected,
  type TranslationQuote,
  type TranslationTarget,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { LanguagesIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useState } from "react";

import { translationJobFinished } from "./use-translation";

/** Why automatic translation cannot be ordered, in the customer's words —
 *  one neutral line, never a dead button. */
export function TranslationUnavailable({
  reasons,
}: {
  reasons: readonly string[];
}) {
  const t = useTranslations("Translations.unavailable");
  const reason = reasons[0] ?? "other";
  return (
    <p className="text-sm text-muted-foreground">
      {t("line", { reason: t.has(reason) ? t(reason) : t("other") })}
    </p>
  );
}

export function TranslateDialog({
  open,
  onOpenChange,
  targets,
  languageName,
  reasonText,
  allowWorking = false,
  offer,
  job,
  onOrdered,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** What to translate, each against the published source. */
  targets: readonly TranslationTarget[];
  languageName: (locale: string) => string;
  /** A review reason in the screen's own words („tryb po akceptacji”…). */
  reasonText: (reason: string) => string;
  /** The source may be translated from its working draft when it has
   *  nothing published to translate from. */
  allowWorking?: boolean;
  /** Who pays: the company's credits, or the platform for its own content. */
  offer: TranslationOffer;
  /** The order this dialog started, as the caller follows it. */
  job?: TranslationJob;
  onOrdered: (job: TranslationJob) => void;
}) {
  const t = useTranslations("Translations.dialog");
  const overwriteId = useId();
  const [quote, setQuote] = useState<TranslationQuote>();
  const [working, setWorking] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [balance, setBalance] = useState<number>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  // A quote that went stale is asked for again.
  const [round, setRound] = useState(0);
  const protectedTexts: TranslationProtected = overwrite
    ? "overwrite"
    : "propose";
  const key = targets
    .map((item) => `${item.source_key}:${item.object_id}:${item.locale}`)
    .join("|");

  useEffect(() => {
    if (!open || job) return;
    let alive = true;
    const asked = targets.map((item) => ({
      ...item,
      basis: working ? ("working" as const) : (item.basis ?? "published"),
    }));
    quoteTranslation(asked, protectedTexts)
      .then((answer) => {
        if (!alive) return;
        // Nothing published to translate from: the draft in the editor.
        if (
          allowWorking &&
          !working &&
          answer.lines.length > 0 &&
          answer.lines.every((line) => line.excluded === "source_unpublished")
        ) {
          setWorking(true);
          return;
        }
        // A note about a stale quote stays beside the new one.
        setQuote(answer);
      })
      .catch(() => {
        if (alive) setMessage(t("quoteFailed"));
      });
    getCustomerCredits()
      .then((credits) => {
        if (alive) setBalance(credits.balance.available);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
    // `key` stands for `targets`: callers build the array on each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, key, working, protectedTexts, allowWorking, job, round, t]);

  async function order() {
    if (!quote) return;
    setBusy(true);
    setMessage("");
    try {
      const started = await orderTranslation(
        targets.map((item) => ({
          ...item,
          basis: working ? "working" : (item.basis ?? "published"),
        })),
        quote,
        crypto.randomUUID(),
        protectedTexts,
      );
      onOrdered(started);
    } catch (error) {
      if (error instanceof ApiProblemError && error.problem.status === 409) {
        // What was quoted is no longer what would be sent: quote again.
        setQuote(undefined);
        setMessage(t("quoteChanged"));
        setRound((value) => value + 1);
      } else setMessage(t("orderFailed"));
    } finally {
      setBusy(false);
    }
  }

  const lines = quote?.lines ?? [];
  const sent = lines.filter((line) => !line.excluded);
  const proposals = lines.reduce((sum, line) => sum + line.proposals, 0);
  const waiting = sent.find((line) => line.outcome === "pending");
  const outcome = waiting?.outcome ?? sent[0]?.outcome;
  const credits =
    quote && offer.billing.mode === "credits" ? quote.credits : undefined;
  const missing =
    credits !== undefined && balance !== undefined && credits > balance
      ? credits - balance
      : 0;
  const nothing = quote !== undefined && quote.units === 0;

  let content;
  if (job) {
    content = (
      <p role="status">
        {translationJobFinished(job)
          ? t.has(`done.${job.state}`)
            ? t(`done.${job.state}`)
            : t("done.succeeded")
          : t("running")}
      </p>
    );
  } else if (!quote) {
    content = <p role="status">{message || t("quoting")}</p>;
  } else {
    content = (
      <div className="space-y-3 text-sm">
        {nothing ? (
          <p>{t("nothing")}</p>
        ) : (
          <>
            <p>
              {t("amount", {
                characters: quote.characters,
                languages: new Set(sent.map((line) => line.locale)).size,
              })}{" "}
              {credits !== undefined
                ? t("costCredits", { credits })
                : t("costPlatform")}{" "}
              {credits !== undefined && balance !== undefined
                ? t("balance", { available: balance })
                : ""}
            </p>
            {missing > 0 && (
              <p className="text-warning-foreground" role="alert">
                {t("insufficient", { missing })}
              </p>
            )}
            {outcome && (
              <p>
                {outcome === "pending"
                  ? t("outcome.pending", {
                      reason: reasonText(waiting?.reason ?? "other"),
                    })
                  : t(outcome === "live" ? "outcome.live" : "outcome.draft")}
              </p>
            )}
            {working && <p className="text-muted-foreground">{t("working")}</p>}
          </>
        )}
        {lines
          .filter((line) => line.excluded)
          .map((line) => (
            <p
              key={`${line.object_id}-${line.locale}`}
              className="text-muted-foreground"
            >
              {t("excluded.line", {
                language: languageName(line.locale),
                reason: t.has(`excluded.${line.excluded}`)
                  ? t(`excluded.${line.excluded}`)
                  : t("excluded.other"),
              })}
            </p>
          ))}
        {(proposals > 0 || overwrite) && (
          <div>
            <label className="flex items-center gap-2" htmlFor={overwriteId}>
              <input
                id={overwriteId}
                type="checkbox"
                checked={overwrite}
                disabled={busy}
                onChange={(event) => {
                  setQuote(undefined);
                  setOverwrite(event.target.checked);
                }}
              />
              {t("overwrite", { count: proposals })}
            </label>
            <p className="text-muted-foreground">{t("overwriteHint")}</p>
          </div>
        )}
        {message && <p role="alert">{message}</p>}
      </div>
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("title")}
          </DialogDescription>
        </DialogHeader>
        {content}
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            {job || nothing ? t("close") : t("cancel")}
          </Button>
          {!job && !nothing && (
            <Button
              type="button"
              disabled={busy || !quote || sent.length === 0 || missing > 0}
              onClick={() => void order()}
            >
              <LanguagesIcon aria-hidden="true" />
              {t("confirm")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
