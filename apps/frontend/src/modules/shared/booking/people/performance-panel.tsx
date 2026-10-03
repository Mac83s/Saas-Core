"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiProblemError,
  getTeamPerformance,
  listTeams,
  type OrganizationSummary,
  type StaffTeam,
  type TeamPerformance,
} from "@saas-core/api-client";
import {
  DataTable,
  DataTableFilter,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";

import { PanelPage, PanelSection } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import { TeamNames } from "../teams/team-names";
import {
  PERIODS,
  periodDays,
  useFactValue,
  useFactWords,
  type PeriodKey,
} from "./person-facts";

type Row = TeamPerformance["items"][number];

/**
 * Zespół › Wydajność (team plan, phase 5, board 7): each person's work in a
 * period, a column per number of every module that counts. The owner's and
 * administrator's view (owner's answer 3); the API refuses anybody else.
 */
/** The facts core itself counts; any other provider is a product's. */
const CORE_PROVIDERS = new Set(["calendar", "inventory", "account"]);

export function PerformancePanel({
  organization,
}: {
  organization: OrganizationSummary | null;
}) {
  const t = useTranslations("StaffFacts");
  const labels = useDataTableLabels();
  const words = useFactWords();
  const zone = organization?.timezone ?? "UTC";
  const value = useFactValue(organization?.currency ?? "PLN");
  const [now] = useState(() => new Date());
  const [period, setPeriod] = useState<PeriodKey>("month");
  const [team, setTeam] = useState("");
  const [teams, setTeams] = useState<StaffTeam[]>([]);
  const [data, setData] = useState<TeamPerformance>();
  const [problem, setProblem] = useState<"access" | "load">();

  useEffect(() => {
    listTeams().then(setTeams, () => setTeams([]));
  }, []);

  useEffect(() => {
    let current = true;
    getTeamPerformance({
      ...periodDays(period, now, zone),
      ...(team ? { team } : {}),
    }).then(
      (next) => {
        if (!current) return;
        setData(next);
        setProblem(undefined);
      },
      (error: unknown) => {
        if (!current) return;
        setProblem(
          error instanceof ApiProblemError && error.problem.status === 403
            ? "access"
            : "load",
        );
      },
    );
    return () => {
      current = false;
    };
  }, [now, period, team, zone]);

  const columns = useMemo<ColumnDef<Row, unknown>[]>(
    () => [
      {
        id: "name",
        accessorKey: "name",
        header: t("column.person"),
        meta: { primary: true },
        cell: ({ row: { original: row } }) => (
          <Link
            className="font-medium text-primary hover:underline"
            href={`/panel/team/${row.staff_id}`}
          >
            {row.name}
          </Link>
        ),
      },
      {
        id: "teams",
        accessorFn: (row) =>
          teams
            .filter((item) => row.team_ids.includes(item.id))
            .map((item) => item.name)
            .join(", "),
        header: t("column.teams"),
        cell: ({ row: { original: row } }) => (
          <TeamNames ids={row.team_ids} teams={teams} />
        ),
      },
      ...(data?.columns ?? []).flatMap((group) =>
        group.metrics.map((metric): ColumnDef<Row, unknown> => ({
          id: `${group.provider}.${metric.key}`,
          accessorFn: (row) => row.groups[group.provider]?.[metric.key] ?? -1,
          header: words.metric(group.provider, metric.key),
          meta: { numeric: true },
          cell: ({ row: { original: row } }) => {
            const number = row.groups[group.provider]?.[metric.key];
            // A person the module has nothing on — no account, no stock —
            // is not a zero.
            return number === undefined ? (
              <span className="text-muted-foreground">{t("noData")}</span>
            ) : (
              <span className="tabular-nums">{value(number, metric.unit)}</span>
            );
          },
        })),
      ),
    ],
    [data, t, teams, value, words],
  );

  return (
    <PanelPage
      description={t("performanceDescription")}
      eyebrow={t("performanceEyebrow")}
      title={t("performanceTitle")}
    >
      {problem === "access" ? (
        <p className="text-muted-foreground">{t("performanceNoAccess")}</p>
      ) : problem === "load" ? (
        <p className="text-sm text-destructive" role="alert">
          {t("loadError")}
        </p>
      ) : (
        <DataTable
          caption={t("performanceCaption")}
          columns={columns}
          data={data?.items ?? []}
          getRowId={(row) => row.staff_id}
          labels={{ ...labels, empty: t("performanceEmpty") }}
          loading={!data}
          searchable
          searchText={(row) => row.name}
          // The period is what the numbers are of: it stays in sight.
          toolbar={
            <DataTableFilter
              id="performance-period"
              label={t("period")}
              onChange={(event) => setPeriod(event.target.value as PeriodKey)}
              value={period}
            >
              {PERIODS.map((key) => (
                <option key={key} value={key}>
                  {t(`period_${key}`)}
                </option>
              ))}
            </DataTableFilter>
          }
          activeFilters={team ? 1 : 0}
          filters={
            teams.length ? (
              <DataTableFilter
                id="performance-team"
                label={t("column.teams")}
                onChange={(event) => setTeam(event.target.value)}
                value={team}
              >
                <option value="">{t("allTeams")}</option>
                {teams.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </DataTableFilter>
            ) : null
          }
        />
      )}
      <PanelSection title={t("howTitle")}>
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          {(
            [
              "visits",
              "hours",
              "used",
              // „Liczby produktu” only where a product counts something (UX-019).
              ...(data?.columns.some(
                (group) => !CORE_PROVIDERS.has(group.provider),
              )
                ? (["product"] as const)
                : []),
            ] as const
          ).map((key) => (
            <div key={key}>
              <dt className="font-medium">{t(`how.${key}.term`)}</dt>
              <dd className="text-muted-foreground">{t(`how.${key}.text`)}</dd>
            </div>
          ))}
        </dl>
      </PanelSection>
    </PanelPage>
  );
}
