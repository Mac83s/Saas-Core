"use client";

import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { FileTextIcon } from "lucide-react";

import {
  listFarmVisits,
  setFarmShareSchedule,
  type FarmShare,
  type FarmVisit,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import {
  DataTable,
  ListSkeleton,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { Label } from "@saas-core/ui/components/label";

import { PanelSection } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";
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
  const common = useTranslations("Common");
  const format = useFormatter();
  const labels = useDataTableLabels();
  // „Teraz" jest z chwili odczytu, nie z renderu: to samo wejście musi dać ten
  // sam podział na przyszłe i przeszłe, ile razy React by go nie policzył.
  const [loaded, setLoaded] = useState<{ now: number; visits: FarmVisit[] }>();
  const [problem, setProblem] = useState<FarmProblem>();
  const [reloads, setReloads] = useState(0);
  const [report, setReport] = useState<FarmVisit>();
  // The row's button gets focus back when the report closes.
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);

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

  if (!loaded) return <ListSkeleton label={t("loadingVisits")} />;

  if (loaded.visits.length === 0)
    return (
      <p className="rounded-xl border border-dashed bg-muted/30 p-6 text-muted-foreground">
        {t("noVisits")}
      </p>
    );

  const day = (visit: FarmVisit) => {
    const date = when(visit);
    return date
      ? format.dateTime(
          date,
          visit.occurred_on
            ? { dateStyle: "medium" }
            : { dateStyle: "medium", timeStyle: "short" },
        )
      : t("unknown");
  };
  const company = (visit: FarmVisit) => visit.company_name || t("unknown");
  // Słowem, nie samym kolorem: status nieznany rdzeniowi pokazujemy tak, jak
  // przyszedł, zamiast zgadywać jego nazwę.
  const status = (visit: FarmVisit) =>
    isKnownStatus(visit.status)
      ? t(`visitStatus_${visit.status}`)
      : visit.status;

  const columns = (withReports: boolean): ColumnDef<FarmVisit, unknown>[] => [
    {
      id: "when",
      // A row with no date at all sorts below every dated one.
      accessorFn: (visit) => when(visit)?.getTime() ?? -1,
      header: t("visitWhen"),
      meta: { primary: true },
      cell: ({ row: { original: visit } }) => (
        <span className="font-medium tabular-nums">{day(visit)}</span>
      ),
    },
    {
      id: "status",
      accessorFn: status,
      header: t("status"),
      cell: ({ row: { original: visit } }) => (
        <Badge variant={visit.status === "canceled" ? "outline" : "secondary"}>
          {status(visit)}
        </Badge>
      ),
    },
    {
      id: "company",
      accessorFn: company,
      header: t("visitCompany"),
      cell: ({ row: { original: visit } }) => (
        <span className="wrap-anywhere">{company(visit)}</span>
      ),
    },
    {
      id: "summary",
      accessorFn: (visit) => visit.summary,
      header: t("visitSummary"),
      enableSorting: false,
      cell: ({ row: { original: visit } }) => (
        <span className="text-muted-foreground wrap-anywhere">
          {visit.summary || "—"}
        </span>
      ),
    },
    ...(withReports
      ? [
          {
            id: "actions",
            header: t("actions"),
            meta: { actions: true },
            cell: ({ row: { original: visit } }) => (
              <RowActions
                items={
                  hasReport(visit)
                    ? [
                        {
                          label: t("visitReportOpen"),
                          icon: <FileTextIcon aria-hidden="true" />,
                          inline: true,
                          onSelect: (trigger: HTMLElement | null) => {
                            setReturnTo(trigger);
                            setReport(visit);
                          },
                        },
                      ]
                    : []
                }
                label={t("actionsFor", {
                  name: `${company(visit)}, ${day(visit)}`,
                })}
              />
            ),
          } satisfies ColumnDef<FarmVisit, unknown>,
        ]
      : []),
  ];

  // Newest first in both groups, one rule; a row with no date at all — a visit
  // called off before it was ever scheduled — closes the list.
  const sorted = [...loaded.visits].sort(
    (first, second) =>
      (when(second)?.getTime() ?? -1) - (when(first)?.getTime() ?? -1),
  );
  const groups = [
    {
      id: "upcoming",
      title: t("visitsUpcoming"),
      empty: t("noUpcomingVisits"),
      visits: sorted.filter((visit) => isUpcoming(visit, loaded.now)),
    },
    {
      id: "past",
      title: t("visitsPast"),
      empty: t("noPastVisits"),
      visits: sorted.filter((visit) => !isUpcoming(visit, loaded.now)),
    },
  ];

  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <PanelSection key={group.id} title={group.title}>
          <DataTable
            caption={t("visitsCaption", { group: group.title })}
            columns={columns(group.visits.some(hasReport))}
            data={group.visits}
            getRowId={(visit) => visit.id}
            labels={{ ...labels, empty: group.empty }}
          />
        </PanelSection>
      ))}
      {report ? (
        <Dialog
          onOpenChange={(open) => {
            if (!open) setReport(undefined);
          }}
          open
        >
          <DialogContent
            className="max-h-[90dvh] overflow-y-auto"
            closeLabel={common("close")}
            finalFocus={() => returnTo ?? true}
          >
            <DialogHeader>
              <DialogTitle>{t("visitReport")}</DialogTitle>
              <DialogDescription>
                {`${day(report)} · ${company(report)}`}
              </DialogDescription>
            </DialogHeader>
            <VisitDetails details={report.details} />
          </DialogContent>
        </Dialog>
      ) : null}
    </div>
  );
}

/** Only a finished visit that came with a report has one to open. */
function hasReport(visit: FarmVisit): boolean {
  return visit.status === "done" && Object.keys(visit.details).length > 0;
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
