"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { listTranslationReview } from "@saas-core/api-client";

import { PageTabs } from "#components/panel/page-tabs";
import { translationComposed } from "./use-translation";

/** „Tłumaczenia”: the overview, what waits for a person and the jobs, one
 *  menu entry (TL16). The views beside the overview exist only where the
 *  engine does and the person may decide — the queue's own answer says so,
 *  and how much waits. */
export function TranslationTabs({
  waiting,
}: {
  /** How much waits, when the page showing the tabs already knows. */
  waiting?: number;
}) {
  const t = useTranslations("Translations.review");
  const [asked, setAsked] = useState<number | null>();
  const known = waiting !== undefined;

  useEffect(() => {
    // Known already, or no engine in this deployment: nothing to ask.
    if (known || !translationComposed()) return;
    let alive = true;
    listTranslationReview({ limit: 1 })
      .then((page) => {
        if (alive) setAsked(page.count);
      })
      .catch(() => {
        // No engine here, or not this person's to decide: no second view.
        if (alive) setAsked(null);
      });
    return () => {
      alive = false;
    };
  }, [known]);

  const count = known ? waiting : asked;
  if (count === undefined || count === null) return null;
  return (
    <PageTabs
      label={t("tabs")}
      tabs={[
        { href: "/panel/sites/translations", label: t("tabOverview") },
        {
          href: "/panel/sites/translations/review",
          label: count ? t("tabReviewCount", { count }) : t("tabReview"),
        },
        { href: "/panel/sites/translations/jobs", label: t("tabJobs") },
      ]}
    />
  );
}
