"use client";

import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { ChevronDownIcon } from "lucide-react";

import {
  listFarmVisits,
  setFarmShareSchedule,
  type FarmShare,
  type FarmVisit,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Label } from "@saas-core/ui/components/label";

import { FarmNotice, focusRing } from "./farms-panel";
import { farmProblem, farmProblemKind, type FarmProblem } from "./problem";

const STATUSES = ["planned", "done", "canceled"] as const;

type VisitStatus = (typeof STATUSES)[number];

function isKnownStatus(status: string): status is VisitStatus {
  return (STATUSES as readonly string[]).includes(status);
}

/** The day the row is about: when it happened, or when somebody is coming. */
function when(visit: FarmVisit): Date | null {
  const raw = visit.occurred_on ?? visit.scheduled_for;
  if (!raw) return null;
  const date = new Date(raw);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * Still ahead: planned *and* dated in the future. A planned visit whose date
 * has passed is history — the company never moved it, and calling it upcoming
 * would be the one thing this screen must not do.
 */
function isUpcoming(visit: FarmVisit, now: number): boolean {
  return (
    visit.status === "planned" &&
    visit.scheduled_for !== null &&
    new Date(visit.scheduled_for).getTime() > now
  );
}

/**
 * The keeper's visits from every company that publishes into this register
 * (ADR-052). Read-only by nature: the rows are written by the companies, and
 * the consent that lets them is on the sharing tab.
 */
export function FarmVisits({ farmId }: { farmId: string }) {
  const t = useTranslations("Farms");
  // „Teraz" jest z chwili odczytu, nie z renderu: to samo wejście musi dać ten
  // sam podział na przyszłe i przeszłe, ile razy React by go nie policzył.
  const [loaded, setLoaded] = useState<{ now: number; visits: FarmVisit[] }>();
  const [problem, setProblem] = useState<FarmProblem>();
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    let current = true;
    listFarmVisits(farmId)
      .then((found) => {
        if (!current) return;
        setLoaded({ now: Date.now(), visits: found });
        setProblem(undefined);
      })
      .catch((error: unknown) => {
        if (current) setProblem(farmProblemKind(error));
      });
    return () => {
      current = false;
    };
  }, [farmId, reloads]);

  if (problem)
    return (
      <FarmNotice
        kind={problem}
        onRetry={() => setReloads((value) => value + 1)}
      />
    );

  if (!loaded)
    return (
      <div aria-busy="true" className="space-y-2">
        <span className="sr-only">{t("loadingVisits")}</span>
        {[0, 1, 2].map((row) => (
          <div className="h-16 animate-pulse rounded-xl bg-muted" key={row} />
        ))}
      </div>
    );

  if (loaded.visits.length === 0)
    return (
      <p className="rounded-xl border border-dashed bg-muted/30 p-6 text-muted-foreground">
        {t("noVisits")}
      </p>
    );

  // Newest first in both groups, one rule; a row with no date at all — a visit
  // called off before it was ever scheduled — closes the list.
  const sorted = [...loaded.visits].sort(
    (first, second) =>
      (when(second)?.getTime() ?? -1) - (when(first)?.getTime() ?? -1),
  );
  const upcoming = sorted.filter((visit) => isUpcoming(visit, loaded.now));
  const past = sorted.filter((visit) => !isUpcoming(visit, loaded.now));

  return (
    <div className="space-y-6">
      <VisitGroup
        empty={t("noUpcomingVisits")}
        title={t("visitsUpcoming")}
        visits={upcoming}
      />
      <VisitGroup
        empty={t("noPastVisits")}
        title={t("visitsPast")}
        visits={past}
      />
    </div>
  );
}

function VisitGroup({
  empty,
  title,
  visits,
}: {
  empty: string;
  title: string;
  visits: FarmVisit[];
}) {
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium text-muted-foreground">{title}</h2>
      {visits.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="space-y-2">
          {visits.map((visit) => (
            <li key={visit.id}>
              <VisitRow visit={visit} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** One visit. A finished one that came with a report opens to show it. */
function VisitRow({ visit }: { visit: FarmVisit }) {
  const t = useTranslations("Farms");
  const hasReport =
    visit.status === "done" && Object.keys(visit.details).length > 0;
  const head = <VisitHead visit={visit} />;

  if (!hasReport) return <div className="rounded-xl border p-4">{head}</div>;

  return (
    <details className="group rounded-xl border">
      <summary
        className={`flex cursor-pointer items-start justify-between gap-3 p-4 ${focusRing}`}
      >
        {head}
        <span className="flex shrink-0 items-center gap-1 text-sm text-muted-foreground">
          {t("visitReport")}
          <ChevronDownIcon
            aria-hidden="true"
            className="size-4 transition-transform group-open:rotate-180"
          />
        </span>
      </summary>
      <div className="border-t p-4">
        <VisitDetails details={visit.details} />
      </div>
    </details>
  );
}

function VisitHead({ visit }: { visit: FarmVisit }) {
  const t = useTranslations("Farms");
  const format = useFormatter();
  const day = when(visit);
  return (
    <div className="min-w-0 space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium tabular-nums">
          {day
            ? format.dateTime(
                day,
                visit.occurred_on
                  ? { dateStyle: "medium" }
                  : { dateStyle: "medium", timeStyle: "short" },
              )
            : t("unknown")}
        </span>
        {/* Słowem, nie samym kolorem: status nieznany rdzeniowi pokazujemy
            tak, jak przyszedł, zamiast zgadywać jego nazwę. */}
        <Badge variant={visit.status === "canceled" ? "outline" : "secondary"}>
          {isKnownStatus(visit.status)
            ? t(`visitStatus_${visit.status}`)
            : visit.status}
        </Badge>
      </div>
      <p className="text-sm wrap-anywhere">
        {visit.company_name || t("unknown")}
      </p>
      {visit.summary ? (
        <p className="text-sm text-muted-foreground wrap-anywhere">
          {visit.summary}
        </p>
      ) : null}
    </div>
  );
}

type DetailRow = { label: string; value: string };
type DetailSection = { title: string; rows: DetailRow[] };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number"
    ? String(value)
    : "";
}

/**
 * The report, as far as the register understands it (ADR-052 pt 7): the
 * vertical publishes labels and values already resolved, because the layer
 * contract forbids core from importing the vertical that knows their codes.
 * Anything that does not fit the shape is dropped rather than guessed at.
 */
function readSections(details: unknown): DetailSection[] {
  const sections = isRecord(details) ? details.sections : undefined;
  if (!Array.isArray(sections)) return [];
  return sections.flatMap((section): DetailSection[] => {
    if (!isRecord(section)) return [];
    const rows = Array.isArray(section.rows) ? section.rows : [];
    const usable = rows.flatMap((row): DetailRow[] => {
      if (!isRecord(row)) return [];
      const label = text(row.label);
      const value = text(row.value);
      return label || value ? [{ label, value }] : [];
    });
    return usable.length > 0
      ? [{ title: text(section.title), rows: usable }]
      : [];
  });
}

function VisitDetails({ details }: { details: Record<string, unknown> }) {
  const t = useTranslations("Farms");
  const sections = readSections(details);

  if (sections.length === 0)
    return (
      <p className="text-sm text-muted-foreground">{t("visitReportUnknown")}</p>
    );

  return (
    <div className="space-y-4">
      {sections.map((section, index) => (
        <section key={`${section.title}-${String(index)}`}>
          {section.title ? (
            <h3 className="text-sm font-medium">{section.title}</h3>
          ) : null}
          <dl className="mt-1 text-sm">
            {section.rows.map((row, rowIndex) => (
              <div
                className="flex flex-wrap justify-between gap-x-6 border-b border-dashed py-1 last:border-0"
                key={`${row.label}-${String(rowIndex)}`}
              >
                <dt className="text-muted-foreground wrap-anywhere">
                  {row.label || "—"}
                </dt>
                <dd className="wrap-anywhere">{row.value || "—"}</dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
    </div>
  );
}

/**
 * The keeper's consent to a company's schedule (ADR-052 pt 4). Off by default
 * and nothing is wrong with that, so the off state says what it means instead
 * of looking like something that failed.
 */
export function ScheduleConsent({
  canManage,
  onChanged,
  share,
}: {
  canManage: boolean;
  onChanged: (share: FarmShare, allowed: boolean) => void;
  share: FarmShare;
}) {
  const t = useTranslations("Farms");
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState("");
  const id = `share-schedule-${share.id}`;
  const partner = share.partner_name || t("unknown");

  async function change(allowed: boolean) {
    setSaving(true);
    setFailed("");
    try {
      onChanged(await setFarmShareSchedule(share.id, allowed), allowed);
    } catch (error) {
      setFailed(farmProblem(error, t("saveFailed")));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-lg bg-muted/40 p-3">
      <div className="flex items-start gap-3">
        <input
          aria-describedby={`${id}-hint`}
          checked={share.can_publish_schedule}
          className={`mt-1 size-4 shrink-0 ${focusRing}`}
          disabled={!canManage || saving}
          id={id}
          onChange={(event) => void change(event.target.checked)}
          type="checkbox"
        />
        <div className="space-y-1">
          <Label htmlFor={id}>{t("scheduleConsent")}</Label>
          <p className="text-sm text-muted-foreground" id={`${id}-hint`}>
            {t("scheduleConsentHint", { name: partner })}
          </p>
          <p className="text-sm text-muted-foreground">
            {share.can_publish_schedule
              ? t("scheduleConsentOn")
              : t("scheduleConsentOff")}
          </p>
        </div>
      </div>
      {failed ? (
        <p className="mt-2 text-sm text-destructive" role="alert">
          {failed}
        </p>
      ) : null}
    </div>
  );
}
