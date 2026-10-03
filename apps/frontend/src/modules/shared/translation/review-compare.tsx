"use client";

/** A waiting translation of a live record (the card, the booking catalogue),
 *  text beside text: the source, what customers read in the language now and
 *  what accepting would write (TL16c). The text waits only in the review
 *  queue, so this is the one place a person can read it before deciding. A
 *  page's waiting text lives in its language editor instead. */

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  ApiProblemError,
  getTranslationReview,
  type TranslationReviewDetail,
  type TranslationReviewItem,
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
import { nativeName } from "#lib/company-locales";

type Unit = TranslationReviewDetail["units"][number];

type Answer =
  | { id: string; detail: TranslationReviewDetail }
  | { id: string; failed: true };

export function ReviewCompareDialog({
  row,
  name,
  reason,
  busy,
  problem,
  onClose,
  onAccept,
  onDiscard,
  onGone,
}: {
  /** The list row being read; nothing while the dialog is closed. */
  row: TranslationReviewItem | undefined;
  name: string;
  reason: string;
  /** A decision is being saved. */
  busy: boolean;
  /** Why the decision was not saved. */
  problem: string;
  onClose: () => void;
  /** The decision at the version this dialog read. */
  onAccept: (detail: TranslationReviewDetail) => void;
  onDiscard: (detail: TranslationReviewDetail) => void;
  /** The item was decided or replaced meanwhile. */
  onGone: () => void;
}) {
  const t = useTranslations("Translations.review");
  const fields = useTranslations("Translations");
  const [answer, setAnswer] = useState<Answer>();
  const [attempt, setAttempt] = useState(0);
  const id = row?.id;

  useEffect(() => {
    if (!id) return;
    let alive = true;
    getTranslationReview(id)
      .then((detail) => {
        if (alive) setAnswer({ id, detail });
      })
      .catch((error: unknown) => {
        if (!alive) return;
        if (error instanceof ApiProblemError && error.problem.status === 404)
          onGone();
        else setAnswer({ id, failed: true });
      });
    return () => {
      alive = false;
    };
    // Asked once per opened item and per „Spróbuj ponownie”.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, attempt]);

  // Another item's answer is not this one's.
  const current = answer?.id === id ? answer : undefined;
  const detail = current && "detail" in current ? current.detail : undefined;
  const failed = current !== undefined && "failed" in current;
  const language = row ? nativeName(row.locale) : "";

  /** What a unit is, in the words of the form it comes from. */
  function fieldOf(unit: Unit): string {
    const part = unit.key.split("/");
    if (unit.key === "headline") return fields("fieldHeadline");
    if (unit.key === "bio") return fields("fieldBio");
    if (part[0] === "link")
      return fields("fieldLinkLabel", { label: unit.source_text });
    const field =
      part[2] === "name"
        ? fields("fieldName")
        : part[2] === "description"
          ? fields("fieldDescription")
          : "";
    const kind = t.has(`compare.items.${part[0]}`)
      ? t(`compare.items.${part[0]}`)
      : "";
    return [kind, field].filter(Boolean).join(" · ");
  }

  return (
    <Dialog
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
      open={row !== undefined}
    >
      <DialogContent className="sm:max-w-4xl" closeLabel={fields("close")}>
        <DialogHeader>
          <DialogTitle>{t("compare.title", { name, language })}</DialogTitle>
          <DialogDescription>{reason}</DialogDescription>
        </DialogHeader>
        {failed ? (
          <div
            className="flex flex-wrap items-center justify-between gap-3 text-sm text-destructive"
            role="alert"
          >
            <span>{t("compare.loadFailed")}</span>
            <Button
              onClick={() => setAttempt((value) => value + 1)}
              size="sm"
              type="button"
              variant="outline"
            >
              {t("retry")}
            </Button>
          </div>
        ) : !detail ? (
          <p className="text-sm text-muted-foreground" role="status">
            {t("compare.loading")}
          </p>
        ) : (
          <>
            {detail.fits ? null : (
              <p
                className="rounded-lg border border-warning-foreground/30 bg-warning p-3 text-sm text-warning-foreground"
                role="alert"
              >
                {t("compare.outdated")}
              </p>
            )}
            <ul
              aria-label={t("compare.list")}
              className="max-h-[55dvh] space-y-4 overflow-y-auto pr-1"
            >
              {detail.units.map((unit) => (
                <li
                  className="rounded-lg border border-border p-3"
                  key={unit.key}
                >
                  {fieldOf(unit) ? (
                    <p className="mb-2 text-sm font-medium wrap-anywhere">
                      {fieldOf(unit)}
                    </p>
                  ) : null}
                  <dl className="grid gap-3 text-sm md:grid-cols-3">
                    <div>
                      <dt className="text-xs text-muted-foreground">
                        {detail.source_locale
                          ? t("compare.sourceIn", {
                              language: nativeName(detail.source_locale),
                            })
                          : t("compare.source")}
                      </dt>
                      <dd
                        className="whitespace-pre-wrap wrap-anywhere"
                        lang={detail.source_locale || undefined}
                      >
                        {unit.source_text || t("compare.sourceGone")}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">
                        {t("compare.current", { language })}
                      </dt>
                      <dd
                        className={
                          unit.current_text
                            ? "whitespace-pre-wrap wrap-anywhere"
                            : "text-muted-foreground"
                        }
                        lang={unit.current_text ? detail.locale : undefined}
                      >
                        {unit.current_text || fields("status_missing")}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">
                        {t("compare.proposed")}
                      </dt>
                      <dd
                        className="font-medium whitespace-pre-wrap wrap-anywhere"
                        lang={detail.locale}
                      >
                        {unit.proposed_text}
                      </dd>
                    </div>
                  </dl>
                </li>
              ))}
            </ul>
          </>
        )}
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
        <DialogFooter>
          <Button
            disabled={busy}
            onClick={onClose}
            type="button"
            variant="outline"
          >
            {fields("close")}
          </Button>
          {detail ? (
            <Button
              disabled={busy}
              onClick={() => onDiscard(detail)}
              type="button"
              variant="outline"
            >
              {t("discard")}
            </Button>
          ) : null}
          {detail && detail.acceptable && detail.fits ? (
            <Button
              disabled={busy}
              onClick={() => onAccept(detail)}
              type="button"
            >
              {t("accept")}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
