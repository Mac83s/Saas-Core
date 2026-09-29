"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { PlusIcon, UserPlusIcon } from "lucide-react";

import type {
  BookingAppointment,
  PeopleDay,
  StaffTeam,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import { cn } from "@saas-core/ui/lib/utils";

import { Link } from "#i18n/navigation";
import { CrewBadges, statusLabel, statusStyle } from "./appointment-dialogs";
import { wallClock } from "./calendar-time";
import {
  boardRange,
  dayState,
  freeWindows,
  hourTicks,
  otherBusy,
  place,
  shortestService,
  type BoardRow,
  type Span,
} from "./day-board-model";
import { todayState } from "./people/people";
import { useTodayText } from "./people/people-panel";
import { TeamNames } from "./teams/team-names";

const focusRing =
  "outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

const NARROW = "(max-width: 767px)";

/** Below 768 px the axis gives way to the agenda (answer 2A, 29.09). */
function useNarrow(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window.matchMedia !== "function") return () => undefined;
      const query = window.matchMedia(NARROW);
      query.addEventListener("change", onChange);
      return () => query.removeEventListener("change", onChange);
    },
    () =>
      typeof window.matchMedia === "function" &&
      window.matchMedia(NARROW).matches,
    () => false,
  );
}

type Handlers = {
  /** A visit's details, as everywhere in the calendar. */
  onOpen: (appointment: BookingAppointment, opener: HTMLElement) => void;
  /** A free window: a new visit for this person at this time. */
  onPlan: (staffId: string, time: string, opener: HTMLElement) => void;
  /** A vacancy: the assignment dialog, for whoever may staff it. */
  onAssign: (appointment: BookingAppointment, opener: HTMLElement) => void;
};

/**
 * Kalendarz › Dzień as the office sees it (plan: phase 4, board 10): a row per
 * person on one axis — hours, absences and visits — with the day's vacancies
 * above them and every free window a way to plan a visit. On a phone the same
 * day is an agenda by person (answer 2A).
 */
export function DayBoard({
  canManage,
  day,
  now,
  peopleDay,
  rows,
  services,
  teams,
  vacancies,
  zone,
  ...handlers
}: Handlers & {
  canManage: boolean;
  day: string;
  now: Date;
  peopleDay: PeopleDay;
  rows: BoardRow[];
  services: { id: string; duration_minutes: number }[];
  teams: StaffTeam[];
  /** The day's visits waiting for somebody (ADR-058 §3). */
  vacancies: BookingAppointment[];
  zone: string;
}) {
  const narrow = useNarrow();
  const t = useTranslations("DayBoard");
  const today = wallClock(now, zone).day === day;
  const todayText = useTodayText(zone);
  const time = (at: number | string) => wallClock(new Date(at), zone).time;
  const span = (item: { starts_at: string; ends_at: string }): Span => ({
    from: Date.parse(item.starts_at),
    to: Date.parse(item.ends_at),
  });

  const lines = rows.map((row) => {
    const visits = row.visits.map(span);
    const takesVisits = Boolean(
      row.person?.service_ids.length && row.person.has_hours,
    );
    // Today says where a person is now; another day, when they work.
    const other = dayState(row.day);
    const state = today
      ? todayText(todayState(row.day, takesVisits, now), now)
      : other.kind === "works"
        ? other.hours
            .map((work) => `${time(work.from)}–${time(work.to)}`)
            .join(", ")
        : t(other.kind === "away" ? "away" : "offDay");
    return {
      row,
      state,
      free: canManage
        ? freeWindows(
            row.day,
            now.getTime(),
            shortestService(row.person, services),
          )
        : [],
      busy: otherBusy(row.day, visits),
    };
  });

  if (narrow)
    return (
      <Agenda
        {...handlers}
        canManage={canManage}
        lines={lines}
        teams={teams}
        time={time}
        vacancies={vacancies}
      />
    );

  const range = boardRange(day, zone, [
    ...peopleDay.items.flatMap((item) => [
      ...item.works.map(span),
      ...item.busy.map(span),
    ]),
    ...rows.flatMap((row) => row.visits.map(span)),
    ...vacancies.map(span),
  ]);
  const ticks = hourTicks(range, zone);
  const nowAt = now.getTime();
  const showNow = today && nowAt > range.from && nowAt < range.to;
  const at = (item: Span) => ({
    left: `${place(item.from, range)}%`,
    width: `${Math.max(place(item.to, range) - place(item.from, range), 0.5)}%`,
  });

  const track = (content: ReactNode, label?: string) => (
    <div
      aria-label={label}
      className="relative min-h-16 flex-1 overflow-hidden rounded-md bg-muted/40"
      role={label ? "group" : undefined}
    >
      {ticks.slice(1, -1).map((tick) => (
        <span
          aria-hidden="true"
          className="absolute inset-y-0 border-l border-border/60"
          key={tick.at}
          style={{ left: `${place(tick.at, range)}%` }}
        />
      ))}
      {content}
      {showNow ? (
        <span
          aria-hidden="true"
          className="absolute inset-y-0 z-10 border-l-2 border-destructive"
          style={{ left: `${place(nowAt, range)}%` }}
        />
      ) : null}
    </div>
  );

  return (
    <div
      aria-label={t("label")}
      className="space-y-2 overflow-x-auto"
      role="region"
    >
      <div className="min-w-[48rem] space-y-2">
        <div aria-hidden="true" className="flex items-end gap-3">
          <span className="w-52 shrink-0 text-xs font-medium text-muted-foreground">
            {t("person")}
          </span>
          <div className="relative h-5 flex-1 text-xs text-muted-foreground tabular-nums">
            {ticks.map((tick, index) =>
              index === ticks.length - 1 ? null : (
                <span
                  className="absolute -translate-x-1/2 first:translate-x-0"
                  key={tick.at}
                  style={{ left: `${place(tick.at, range)}%` }}
                >
                  {tick.label}
                </span>
              ),
            )}
            {showNow ? (
              <span
                className="absolute -translate-x-1/2 rounded bg-destructive px-1 font-medium text-white"
                style={{ left: `${place(nowAt, range)}%` }}
              >
                {time(nowAt)}
              </span>
            ) : null}
          </div>
        </div>

        {vacancies.length ? (
          <div className="flex items-stretch gap-3">
            <div className="w-52 shrink-0 space-y-0.5 py-1">
              <p className="text-sm font-semibold">
                {t("vacancies", { count: vacancies.length })}
              </p>
              <p className="text-xs text-muted-foreground">
                {t("vacanciesHint")}
              </p>
            </div>
            {track(
              vacancies.map((item) => (
                <button
                  aria-label={t("assignLabel", {
                    customer: item.customer_name,
                    service: item.service_name,
                    when: `${time(item.starts_at)}–${time(item.ends_at)}`,
                  })}
                  className={cn(
                    "absolute inset-y-1.5 z-[1] flex min-w-0 flex-col overflow-hidden rounded-md border-2 border-dashed border-warning-foreground bg-warning px-1.5 py-1 text-left text-xs text-warning-foreground hover:brightness-95",
                    focusRing,
                  )}
                  key={item.id}
                  onClick={(event) =>
                    canManage
                      ? handlers.onAssign(item, event.currentTarget)
                      : handlers.onOpen(item, event.currentTarget)
                  }
                  style={at(span(item))}
                  type="button"
                >
                  <span className="truncate font-semibold">
                    {item.customer_name}
                  </span>
                  <span className="truncate">{item.service_name}</span>
                </button>
              )),
            )}
          </div>
        ) : null}

        {lines.map(({ row, state, free, busy }) => (
          <div className="flex items-stretch gap-3" key={row.staffId}>
            <div className="w-52 shrink-0 space-y-0.5 py-1">
              <Link
                className={cn(
                  "block truncate text-sm font-semibold hover:underline",
                  focusRing,
                )}
                href={`/panel/team/${row.staffId}`}
              >
                {row.name}
              </Link>
              <p className="truncate text-xs text-muted-foreground">{state}</p>
              {row.person?.team_ids.length ? (
                <p className="truncate text-xs text-muted-foreground">
                  <TeamNames ids={row.person.team_ids} teams={teams} />
                </p>
              ) : null}
            </div>
            {track(
              <>
                {/* Outside the hours is hatched; the hours are the plain ground. */}
                <span
                  aria-hidden="true"
                  className="absolute inset-0 bg-[repeating-linear-gradient(135deg,transparent_0_6px,var(--color-border)_6px_7px)]"
                />
                {row.day?.works.map((work) => (
                  <span
                    aria-hidden="true"
                    className="absolute inset-y-0 bg-background"
                    key={work.starts_at}
                    style={at(span(work))}
                  />
                ))}
                {row.day?.time_off.map((away) => (
                  <span
                    className="absolute inset-y-1.5 z-[1] flex items-center overflow-hidden rounded-md bg-muted px-1.5 text-xs text-muted-foreground"
                    key={away.starts_at}
                    style={at(span(away))}
                  >
                    <span className="truncate">
                      {away.reason
                        ? `${t("awayBlock")}: ${away.reason}`
                        : t("awayBlock")}
                    </span>
                  </span>
                ))}
                {busy.map((block) => (
                  <span
                    className="absolute inset-y-1.5 z-[1] flex items-center overflow-hidden rounded-md border bg-muted px-1.5 text-xs text-muted-foreground"
                    key={block.from}
                    style={at(block)}
                  >
                    <span className="truncate">
                      {t("busy", {
                        from: time(block.from),
                        to: time(block.to),
                      })}
                    </span>
                  </span>
                ))}
                {free.map((window) => (
                  <button
                    aria-label={t("planLabel", {
                      name: row.name,
                      from: time(window.from),
                      to: time(window.to),
                    })}
                    className={cn(
                      "group absolute inset-y-1.5 z-[1] flex items-center justify-center rounded-md text-xs text-muted-foreground hover:border hover:border-dashed hover:border-primary hover:bg-primary/5 hover:text-primary",
                      focusRing,
                    )}
                    key={window.from}
                    onClick={(event) =>
                      handlers.onPlan(
                        row.staffId,
                        time(window.from),
                        event.currentTarget,
                      )
                    }
                    style={at(window)}
                    type="button"
                  >
                    <PlusIcon
                      aria-hidden="true"
                      className="size-4 opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100"
                    />
                  </button>
                ))}
                {row.visits.map((item) => (
                  <VisitBlock
                    item={item}
                    key={item.id}
                    lead={item.staff_id === row.staffId && item.crew.length > 1}
                    onOpen={handlers.onOpen}
                    style={at(span(item))}
                    time={time}
                  />
                ))}
              </>,
              row.name,
            )}
          </div>
        ))}

        <Legend />
      </div>
    </div>
  );
}

function VisitBlock({
  item,
  lead,
  onOpen,
  style,
  time,
}: {
  item: BookingAppointment;
  lead: boolean;
  onOpen: Handlers["onOpen"];
  style: { left: string; width: string };
  time: (at: string) => string;
}) {
  const t = useTranslations("DayBoard");
  const calendar = useTranslations("Calendar");
  const { className } = statusStyle(item.status);
  const when = `${time(item.starts_at)}–${time(item.ends_at)}`;
  return (
    <button
      aria-label={[
        when,
        item.customer_name,
        item.service_name,
        statusLabel(calendar, item.status),
        lead ? t("leads") : "",
        item.auto_assigned ? calendar("auto") : "",
      ]
        .filter(Boolean)
        .join(", ")}
      className={cn(
        "absolute inset-y-1.5 z-[2] flex min-w-0 flex-col overflow-hidden rounded-md border px-1.5 py-1 text-left text-xs hover:brightness-95",
        className,
        focusRing,
      )}
      onClick={(event) => onOpen(item, event.currentTarget)}
      style={style}
      type="button"
    >
      <span className="flex min-w-0 items-center gap-1 font-semibold">
        {lead ? (
          <span className="shrink-0 rounded-sm bg-background/60 px-1">
            {t("leadShort")}
          </span>
        ) : null}
        <span className="truncate">{item.customer_name}</span>
        {item.auto_assigned && !item.needs_assignment ? (
          <span className="shrink-0 rounded-sm bg-background/60 px-1">
            {calendar("autoShort")}
          </span>
        ) : null}
      </span>
      <span className="truncate">
        {item.service_name} · {when}
      </span>
    </button>
  );
}

function Legend() {
  const t = useTranslations("DayBoard");
  const calendar = useTranslations("Calendar");
  const swatch = "inline-block h-3 w-5 rounded-sm border";
  return (
    <ul
      aria-label={t("legend")}
      className="flex flex-wrap gap-x-4 gap-y-1 pt-2 text-xs text-muted-foreground"
    >
      {(["confirmed", "completed"] as const).map((status) => (
        <li className="flex items-center gap-1.5" key={status}>
          <span className={cn(swatch, statusStyle(status).className)} />
          {statusLabel(calendar, status)}
        </li>
      ))}
      <li className="flex items-center gap-1.5">
        <span
          className={cn(
            swatch,
            "border-2 border-dashed border-warning-foreground bg-warning",
          )}
        />
        {t("legendVacancy")}
      </li>
      <li className="flex items-center gap-1.5">
        <span className={cn(swatch, "bg-muted")} />
        {t("awayBlock")}
      </li>
      <li className="flex items-center gap-1.5">
        <span
          className={cn(
            swatch,
            "bg-[repeating-linear-gradient(135deg,transparent_0_3px,var(--color-border)_3px_4px)]",
          )}
        />
        {t("legendOff")}
      </li>
      <li>{t("legendLead")}</li>
    </ul>
  );
}

type Line = {
  row: BoardRow;
  state: string;
  free: Span[];
  busy: Span[];
};

/** The phone's day: vacancies first, then each person's day in order. */
function Agenda({
  canManage,
  lines,
  onAssign,
  onOpen,
  onPlan,
  teams,
  time,
  vacancies,
}: Handlers & {
  canManage: boolean;
  lines: Line[];
  teams: StaffTeam[];
  time: (at: number | string) => string;
  vacancies: BookingAppointment[];
}) {
  const t = useTranslations("DayBoard");
  const card =
    "flex min-h-11 w-full flex-col items-start gap-0.5 rounded-lg border p-2.5 text-left text-sm";
  return (
    <div aria-label={t("label")} className="space-y-4" role="region">
      {vacancies.length ? (
        <section aria-labelledby="agenda-vacancies" className="space-y-2">
          <h3 className="text-sm font-semibold" id="agenda-vacancies">
            {t("vacancies", { count: vacancies.length })}
          </h3>
          <ul className="space-y-2">
            {vacancies.map((item) => (
              <li
                className={cn(
                  card,
                  "border-2 border-dashed border-warning-foreground bg-warning/40",
                )}
                key={item.id}
              >
                <span className="font-semibold tabular-nums">
                  {time(item.starts_at)}–{time(item.ends_at)}
                </span>
                <span className="font-medium">{item.customer_name}</span>
                <span className="text-xs text-muted-foreground">
                  {item.service_name}
                </span>
                <Button
                  className="mt-1"
                  onClick={(event) =>
                    canManage
                      ? onAssign(item, event.currentTarget)
                      : onOpen(item, event.currentTarget)
                  }
                  size="sm"
                  variant="outline"
                >
                  <UserPlusIcon aria-hidden="true" />
                  {canManage ? t("assign") : t("details")}
                  <span className="sr-only">: {item.customer_name}</span>
                </Button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {lines.map(({ row, state, free, busy }) => {
        const entries = [
          ...row.visits.map((item) => ({
            at: Date.parse(item.starts_at),
            node: (
              <button
                className={cn(
                  card,
                  "border-l-4 hover:bg-muted",
                  statusStyle(item.status).border,
                  focusRing,
                )}
                onClick={(event) => onOpen(item, event.currentTarget)}
                type="button"
              >
                <span className="font-semibold tabular-nums">
                  {time(item.starts_at)}–{time(item.ends_at)}
                </span>
                <span className="font-medium">{item.customer_name}</span>
                <span className="text-xs text-muted-foreground">
                  {item.service_name}
                </span>
                <span className="flex flex-wrap gap-1">
                  {item.staff_id === row.staffId && item.crew.length > 1 ? (
                    <span className="rounded-sm bg-muted px-1 text-xs">
                      {t("leads")}
                    </span>
                  ) : null}
                  <CrewBadges appointment={item} short />
                </span>
              </button>
            ),
          })),
          ...(row.day?.time_off ?? []).map((away) => ({
            at: Date.parse(away.starts_at),
            node: (
              <p className={cn(card, "bg-muted text-muted-foreground")}>
                {away.reason
                  ? `${t("awayBlock")}: ${away.reason}`
                  : t("awayBlock")}{" "}
                {t("range", {
                  from: time(away.starts_at),
                  to: time(away.ends_at),
                })}
              </p>
            ),
          })),
          ...busy.map((block) => ({
            at: block.from,
            node: (
              <p className={cn(card, "text-muted-foreground")}>
                {t("busy", { from: time(block.from), to: time(block.to) })}
              </p>
            ),
          })),
          ...free.map((window) => ({
            at: window.from,
            node: (
              <div
                className={cn(
                  card,
                  "flex-row items-center justify-between border-dashed text-muted-foreground",
                )}
              >
                <span>
                  {t("free", { from: time(window.from), to: time(window.to) })}
                </span>
                <Button
                  aria-label={t("planLabel", {
                    name: row.name,
                    from: time(window.from),
                    to: time(window.to),
                  })}
                  onClick={(event) =>
                    onPlan(row.staffId, time(window.from), event.currentTarget)
                  }
                  size="sm"
                  variant="outline"
                >
                  <PlusIcon aria-hidden="true" />
                  {t("plan")}
                </Button>
              </div>
            ),
          })),
        ].sort((a, b) => a.at - b.at);
        const heading = `agenda-${row.staffId}`;
        return (
          <section
            aria-labelledby={heading}
            className="space-y-2"
            key={row.staffId}
          >
            <div>
              <h3 className="text-sm font-semibold" id={heading}>
                <Link
                  className={cn("hover:underline", focusRing)}
                  href={`/panel/team/${row.staffId}`}
                >
                  {row.name}
                </Link>
              </h3>
              <p className="text-xs text-muted-foreground">
                {state}
                {row.person?.team_ids.length ? (
                  <>
                    {" · "}
                    <TeamNames ids={row.person.team_ids} teams={teams} />
                  </>
                ) : null}
              </p>
            </div>
            {entries.length ? (
              <ol className="space-y-2">
                {entries.map((entry, index) => (
                  <li key={`${entry.at}-${index}`}>{entry.node}</li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-muted-foreground">{t("nothing")}</p>
            )}
          </section>
        );
      })}
    </div>
  );
}
