"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ArrowRightIcon, CheckCircle2Icon, CircleIcon } from "lucide-react";

import {
  listFarmAnimals,
  listFarms,
  listFarmShares,
  listFollowUps,
  listRegisterVisits,
  type Farm,
  type FarmAnimal,
  type FollowUp,
  type RegisterVisit,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { cn } from "@saas-core/ui/lib/utils";

import { PanelPage, PanelSection } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { formatDate, formatDateTime } from "#lib/dates";
import type { ProductDashboardProps } from "#lib/product-extension";
import { VisitDetails } from "./farm-visits";

/** How many of each a block lists; the rest is one click away. */
const SHOWN = 5;

type Loaded = {
  farms: Farm[];
  linked: boolean;
  review: number;
  withdrawal: FarmAnimal[];
  coming: RegisterVisit[];
  reports: RegisterVisit[];
  controls: FollowUp[];
};

const dayKey = (date: Date) => date.toISOString().slice(0, 10);

/**
 * „Dziś” of a farm (UX-078): what the keeper comes for — animals the companies
 * wrote in, waiting to be looked at; the companies' visits ahead; controls
 * due; the latest reports; animals in withdrawal — and, until it is done, the
 * keeper's own start: a farm linked to a company, its herd number, its animals.
 * Core `shared.farms`; a product gives it to its farm type in the dashboard
 * slot, so the service company's start page never reaches a farm.
 */
export function FarmerToday({ firstName }: ProductDashboardProps) {
  const t = useTranslations("FarmerToday");
  const farmsText = useTranslations("Farms");
  const locale = useLocale();
  const [data, setData] = useState<Loaded>();
  const [failed, setFailed] = useState(false);
  const [report, setReport] = useState<RegisterVisit>();

  const load = useCallback(async () => {
    setFailed(false);
    const now = new Date();
    const today = dayKey(now);
    const quarterAgo = dayKey(new Date(now.getTime() - 90 * 86_400_000));
    try {
      const [farms, review, animals, coming, done, controls] =
        await Promise.all([
          listFarms(),
          listFarmAnimals({ review: true }),
          listFarmAnimals(),
          listRegisterVisits({ from: today, status: "planned" }),
          listRegisterVisits({ from: quarterAgo, to: today, status: "done" }),
          listFollowUps({ from: today }),
        ]);
      // A handful of farms at most: whether any of them works with a company.
      const shares = await Promise.all(
        farms.map((farm) => listFarmShares(farm.id)),
      );
      const running = (until: string | null) =>
        until !== null && Date.parse(until) > now.getTime();
      setData({
        farms,
        linked: shares
          .flat()
          .some(
            (share) => share.partner_is_company && share.status === "active",
          ),
        review: review.length,
        withdrawal: animals.filter(
          (animal) =>
            running(animal.withdrawal_milk_until) ||
            running(animal.withdrawal_meat_until),
        ),
        coming: coming.filter(
          (visit) =>
            visit.scheduled_for !== null &&
            Date.parse(visit.scheduled_for) > now.getTime(),
        ),
        reports: [...done].reverse(),
        controls,
      });
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    void load();
  }, [load]);

  const animalName = (control: FollowUp) =>
    [control.national_id, control.working_number || control.animal_name]
      .filter(Boolean)
      .join(" · ");

  return (
    <PanelPage
      description={t("description")}
      title={firstName ? t("greeting", { name: firstName }) : t("title")}
    >
      {failed ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{t("loadError")}</p>
          <Button onClick={() => void load()} variant="outline">
            {t("retry")}
          </Button>
        </div>
      ) : !data ? (
        <div
          aria-busy="true"
          className="h-48 animate-pulse rounded-lg bg-muted"
        />
      ) : (
        <div className="space-y-8">
          <Start data={data} />
          <PanelSection
            actions={
              data.review ? (
                <Link
                  className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
                  href="/panel/animals?review=1"
                >
                  {t("reviewOpen")}
                  <ArrowRightIcon aria-hidden="true" className="size-4" />
                </Link>
              ) : null
            }
            title={t("reviewTitle", { count: data.review })}
          >
            <p className="text-sm text-muted-foreground">
              {data.review
                ? t("reviewText", { count: data.review })
                : t("reviewNone")}
            </p>
          </PanelSection>

          <PanelSection title={t("comingTitle")}>
            {data.coming.length ? (
              <ol className="divide-y rounded-lg border">
                {data.coming.slice(0, SHOWN).map((visit) => (
                  <li className="p-3 text-sm" key={visit.id}>
                    <p className="font-medium">
                      {visit.scheduled_for
                        ? formatDateTime(visit.scheduled_for, locale)
                        : "—"}
                    </p>
                    <p className="text-muted-foreground wrap-anywhere">
                      {[visit.company_name, visit.farm_name, visit.summary]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-muted-foreground">{t("comingNone")}</p>
            )}
          </PanelSection>

          <PanelSection title={t("controlsTitle")}>
            {data.controls.length ? (
              <ol className="divide-y rounded-lg border">
                {data.controls.slice(0, SHOWN).map((control) => (
                  <li className="p-3 text-sm" key={control.entry_id}>
                    <p className="font-medium">
                      {formatDate(control.follow_up_on, locale)} ·{" "}
                      {animalName(control)}
                    </p>
                    <p className="text-muted-foreground wrap-anywhere">
                      {[
                        control.farm_name,
                        control.author_organization_name,
                        control.summary,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("controlsNone")}
              </p>
            )}
          </PanelSection>

          <PanelSection
            description={t("reportsHint")}
            title={t("reportsTitle")}
          >
            {data.reports.length ? (
              <ol className="divide-y rounded-lg border">
                {data.reports.slice(0, SHOWN).map((visit) => (
                  <li
                    className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm"
                    key={visit.id}
                  >
                    <span className="min-w-0">
                      <span className="block font-medium">
                        {visit.occurred_on
                          ? formatDate(visit.occurred_on, locale)
                          : "—"}{" "}
                        · {visit.company_name}
                      </span>
                      <span className="block text-muted-foreground wrap-anywhere">
                        {[visit.farm_name, visit.summary]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </span>
                    <Button
                      onClick={() => setReport(visit)}
                      size="sm"
                      variant="outline"
                    >
                      {farmsText("visitReportOpen")}
                    </Button>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("reportsNone")}
              </p>
            )}
          </PanelSection>

          <PanelSection title={t("withdrawalTitle")}>
            {data.withdrawal.length ? (
              <ol className="divide-y rounded-lg border">
                {data.withdrawal.slice(0, SHOWN).map((animal) => (
                  <li className="p-3 text-sm" key={animal.id}>
                    <p className="font-medium">
                      {[
                        animal.national_id,
                        animal.working_number || animal.name,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                    <p className="text-muted-foreground">
                      {[
                        animal.withdrawal_milk_until
                          ? t("withdrawalMilk", {
                              date: formatDate(
                                animal.withdrawal_milk_until,
                                locale,
                              ),
                            })
                          : null,
                        animal.withdrawal_meat_until
                          ? t("withdrawalMeat", {
                              date: formatDate(
                                animal.withdrawal_meat_until,
                                locale,
                              ),
                            })
                          : null,
                        animal.farm_name,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("withdrawalNone")}
              </p>
            )}
          </PanelSection>
        </div>
      )}
      {report ? (
        <Dialog
          onOpenChange={(open) => (open ? undefined : setReport(undefined))}
          open
        >
          <DialogContent
            className="max-h-[90dvh] overflow-y-auto"
            closeLabel={t("close")}
          >
            <DialogHeader>
              <DialogTitle>{farmsText("visitReport")}</DialogTitle>
              <DialogDescription>
                {[
                  report.occurred_on
                    ? formatDate(report.occurred_on, locale)
                    : null,
                  report.company_name,
                  report.farm_name,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </DialogDescription>
            </DialogHeader>
            <VisitDetails details={report.details} />
            <p className="text-sm text-muted-foreground">{t("pdfByEmail")}</p>
          </DialogContent>
        </Dialog>
      ) : null}
    </PanelPage>
  );
}

/** The keeper's own start — hidden once every step is done. */
function Start({ data }: { data: Loaded }) {
  const t = useTranslations("FarmerToday");
  const firstWithoutNumber = data.farms.find((farm) => !farm.herd_number);
  const steps = [
    { key: "link", done: data.linked, href: "/panel/farms" },
    {
      key: "herd",
      done: data.farms.length > 0 && !firstWithoutNumber,
      href: firstWithoutNumber
        ? `/panel/farms/${firstWithoutNumber.id}`
        : "/panel/farms",
    },
    {
      key: "animals",
      done: data.farms.some((farm) => (farm.animal_count ?? 0) > 0),
      href: "/panel/animals",
    },
  ] as const;
  if (steps.every((step) => step.done)) return null;
  return (
    <PanelSection title={t("startTitle")}>
      <ol className="space-y-2">
        {steps.map((step) => (
          <li className="flex items-start gap-2 text-sm" key={step.key}>
            {step.done ? (
              <CheckCircle2Icon
                aria-hidden="true"
                className="mt-0.5 size-4 shrink-0 text-success-foreground"
              />
            ) : (
              <CircleIcon
                aria-hidden="true"
                className="mt-0.5 size-4 shrink-0 text-muted-foreground"
              />
            )}
            <span
              className={cn(step.done && "text-muted-foreground line-through")}
            >
              {step.done ? (
                <>
                  <span className="sr-only">{t("stepDone")} </span>
                  {t(`step_${step.key}`)}
                </>
              ) : (
                <Link
                  className="font-medium text-primary hover:underline"
                  href={step.href}
                >
                  {t(`step_${step.key}`)}
                </Link>
              )}
            </span>
          </li>
        ))}
      </ol>
    </PanelSection>
  );
}
