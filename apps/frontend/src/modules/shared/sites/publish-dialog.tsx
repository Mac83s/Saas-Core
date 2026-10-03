"use client";

/** Before the whole site is published: what each other language would
 *  carry (TL15). The site's own language always goes out in full; in the
 *  others what is ready goes out and the rest never blocks — so the dialog
 *  says per language whether visitors will read the site in it, and names
 *  only the pages that need a look, each with the way to its editor. */

import {
  previewSitePublication,
  type PublicationPlan,
  type SiteLocalizationReport,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { RocketIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { Link } from "#i18n/navigation";
import type { CompanyLocale } from "#lib/company-locales";

const ATTENTION = new Set([
  "carried",
  "withheld",
  "withdrawn",
  "skipped",
  "missing",
]);

export function PublishDialog({
  open,
  onOpenChange,
  siteId,
  report,
  locales,
  publishing,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  siteId: string;
  report: SiteLocalizationReport;
  /** The company's languages with their own names. */
  locales: readonly CompanyLocale[];
  publishing: boolean;
  onConfirm: () => void;
}) {
  const t = useTranslations("Sites.publishDialog");
  const mode = useTranslations("Sites.languageMode");
  const common = useTranslations("Common");
  const [plan, setPlan] = useState<PublicationPlan | "error">();
  useEffect(() => {
    if (!open) return;
    let active = true;
    previewSitePublication(siteId)
      .then((loaded) => {
        if (active) setPlan(loaded);
      })
      .catch(() => {
        if (active) setPlan("error");
      });
    return () => {
      active = false;
    };
  }, [open, siteId]);
  const nameOf = (code: string) =>
    locales.find((item) => item.code === code)?.name ?? code.toUpperCase();

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !publishing && onOpenChange(next)}
    >
      <DialogContent
        closeLabel={common("close")}
        className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl"
      >
        <DialogTitle>{t("title")}</DialogTitle>
        <DialogDescription>
          {t("description", { language: nameOf(report.default_locale) })}
        </DialogDescription>
        {plan === undefined && (
          <p className="text-sm text-muted-foreground" role="status">
            {t("loading")}
          </p>
        )}
        {plan === "error" && (
          <p className="text-sm" role="alert">
            {t("loadError")}
          </p>
        )}
        {plan && plan !== "error" && (
          <ul className="space-y-3">
            {plan.languages.map((language) => {
              const count = (outcome: string) =>
                language.pages.filter((page) => page.outcome === outcome)
                  .length;
              const attention = language.pages.filter((page) =>
                ATTENTION.has(page.outcome),
              );
              return (
                <li key={language.locale} className="rounded-lg border p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium" lang={language.locale}>
                      {nameOf(language.locale)}
                    </span>
                    <Badge
                      variant={
                        language.live_after
                          ? "success"
                          : attention.length
                            ? "warning"
                            : "neutral"
                      }
                    >
                      {t(
                        language.live_after
                          ? language.live
                            ? "live.stays"
                            : "live.appears"
                          : "live.notYet",
                      )}
                    </Badge>
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {t("summary", {
                      publish: count("publish"),
                      unchanged: count("unchanged"),
                      attention: attention.length,
                    })}
                  </p>
                  {attention.length > 0 && (
                    <ul className="mt-2 space-y-1 text-sm">
                      {attention.map((page) => (
                        <li
                          key={page.page_id}
                          className="flex flex-wrap items-baseline justify-between gap-x-3"
                        >
                          <span>
                            <span className="font-medium">
                              {page.page_name}
                            </span>
                            {" — "}
                            {t(`outcomes.${page.outcome}`)}
                            {page.reason &&
                            page.outcome !== "withheld" &&
                            mode.has(`skipped.${page.reason}`)
                              ? `: ${mode(`skipped.${page.reason}`)}`
                              : ""}
                          </span>
                          <Link
                            className="text-primary underline"
                            href={`/panel/sites/pages/${page.page_id}?language=${language.locale}`}
                            aria-label={t("open", {
                              page: page.page_name,
                              language: nameOf(language.locale),
                            })}
                          >
                            {t("openShort")}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={publishing}
            onClick={() => onOpenChange(false)}
          >
            {common("cancel")}
          </Button>
          <Button
            type="button"
            disabled={publishing || plan === undefined}
            onClick={onConfirm}
          >
            <RocketIcon aria-hidden="true" />
            {t("confirm")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
