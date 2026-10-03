"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";

import {
  getBookingOccupancy,
  type BookingOccupancy,
  type OccupancyHeld,
  type OccupancyUnit,
  type OrganizationSummary,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import { DataTableFilter } from "@saas-core/ui/components/data-table";
import { cn } from "@saas-core/ui/lib/utils";

import { PanelPage, PanelToolbar } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { formatDateRange, formatVisit } from "#lib/dates";
import { shownStatus, StatusBadge, statusStyle } from "../appointment-dialogs";
import { addDays, formatDay, wallClock, zonedInstant } from "../calendar-time";

const BOOKING_MANAGE = "booking.appointment.manage";
/** Two weeks on the screen; the arrows move one week. */
const DAYS = 14;

const BLOCK =
  "border border-dashed border-muted-foreground bg-muted text-muted-foreground";
/** The calendar's „Poza grafikiem” hatch: a day nobody is booked on. */
const CLOSED =
  "bg-[repeating-linear-gradient(135deg,transparent_0_6px,var(--color-border)_6px_7px)]";

/** A booking in the calendar's own colours, passed or not (UX-031). */
const heldStyle = (item: OccupancyHeld) =>
  item.kind === "block" ? BLOCK : statusStyle(shownStatus(item)).className;

/**
 * Kalendarz › Obłożenie (ADR-072 phase 2d): every unit against two weeks of
 * days, with what holds it — a stay, a visit that takes the room, a block —
 * and the days its place or the company is closed. A stay arrives in the
 * afternoon and leaves in the morning, so its bar starts and ends mid-day.
 */
export function OccupancyPanel({
  organization,
}: {
  organization: OrganizationSummary | null;
}) {
  const t = useTranslations("Occupancy");
  const calendar = useTranslations("Calendar");
  const locale = useLocale();
  const zone = organization?.timezone ?? "UTC";
  const canManage = Boolean(organization?.permissions.includes(BOOKING_MANAGE));
  const [today] = useState(() => wallClock(new Date(), zone).day);
  const [first, setFirst] = useState(today);
  const [groupId, setGroupId] = useState("");
  const [data, setData] = useState<BookingOccupancy>();
  const [failed, setFailed] = useState(false);
  const last = addDays(first, DAYS - 1);

  const load = useCallback(async () => {
    setFailed(false);
    try {
      setData(
        await getBookingOccupancy({
          from: first,
          to: last,
          ...(groupId ? { group_id: groupId } : {}),
        }),
      );
    } catch {
      setFailed(true);
    }
  }, [first, groupId, last]);

  useEffect(() => {
    if (!canManage) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load on window change
    void load();
  }, [canManage, load]);

  // The groups come with the units; a choice of one stays in the list.
  const [groups, setGroups] = useState<{ id: string; name: string }[]>([]);
  useEffect(() => {
    if (!data || groupId) return;
    const seen = new Map<string, string>();
    for (const unit of data.units)
      if (unit.group_id && unit.group_name)
        seen.set(unit.group_id, unit.group_name);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- derived from the first load
    setGroups([...seen].map(([id, name]) => ({ id, name })));
  }, [data, groupId]);

  const days = useMemo(
    () => Array.from({ length: DAYS }, (_, index) => addDays(first, index)),
    [first],
  );
  const range = formatDateRange(first, last, locale);
  const empty = data !== undefined && !data.units.length;

  return (
    <PanelPage description={t("description")} title={t("title")}>
      {!canManage ? (
        <p className="text-muted-foreground">{t("noAccess")}</p>
      ) : empty ? (
        // UX-021: nothing to show yet — one sentence and where to change it.
        <p className="text-sm text-muted-foreground">
          {t("noUnits")}{" "}
          <Link
            className="font-medium text-primary hover:underline"
            href="/panel/settings/services"
          >
            {t("settingsLink")}
          </Link>
        </p>
      ) : (
        <section aria-labelledby="occupancy-range" className="space-y-3">
          <PanelToolbar>
            <Button
              disabled={first === today}
              onClick={() => setFirst(today)}
              variant="outline"
            >
              {calendar("today")}
            </Button>
            <Button
              aria-label={calendar("previous_week")}
              onClick={() => setFirst(addDays(first, -7))}
              size="icon"
              variant="outline"
            >
              <ChevronLeftIcon aria-hidden="true" />
            </Button>
            <Button
              aria-label={calendar("next_week")}
              onClick={() => setFirst(addDays(first, 7))}
              size="icon"
              variant="outline"
            >
              <ChevronRightIcon aria-hidden="true" />
            </Button>
            <h2
              aria-live="polite"
              className="ml-1 text-lg font-semibold sm:text-xl"
              id="occupancy-range"
            >
              {range}
            </h2>
            {groups.length > 1 ? (
              <div className="sm:ml-auto">
                <DataTableFilter
                  id="occupancy-group"
                  label={t("group")}
                  onChange={(event) => setGroupId(event.target.value)}
                  value={groupId}
                >
                  <option value="">{t("allGroups")}</option>
                  {groups.map((group) => (
                    <option key={group.id} value={group.id}>
                      {group.name}
                    </option>
                  ))}
                </DataTableFilter>
              </div>
            ) : null}
          </PanelToolbar>
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
            <>
              <Grid data={data} days={days} today={today} zone={zone} />
              <Agenda data={data} zone={zone} />
              <Legend />
            </>
          )}
        </section>
      )}
    </PanelPage>
  );
}

function useHeldText(zone: string) {
  const t = useTranslations("Occupancy");
  const locale = useLocale();
  // A visit is a day and its hours; a stay and a block run over days.
  const when = (item: OccupancyHeld) =>
    item.kind === "visit"
      ? formatVisit(item.starts_at, item.ends_at, locale, zone)
      : formatDateRange(item.starts_at, item.ends_at, locale, zone);
  return (item: OccupancyHeld) =>
    item.kind === "block"
      ? item.title
        ? t("heldBlock", { title: item.title, when: when(item) })
        : t("heldBlockBare", { when: when(item) })
      : t(item.kind === "stay" ? "heldStay" : "heldVisit", {
          title: item.title,
          when: when(item),
        });
}

/** A day's link in the calendar: where a booking is opened and changed. */
const dayHref = (item: OccupancyHeld, zone: string) =>
  `/panel/calendar?view=day&date=${wallClock(item.starts_at, zone).day}`;

function Grid({
  data,
  days,
  today,
  zone,
}: {
  data: BookingOccupancy;
  days: string[];
  today: string;
  zone: string;
}) {
  const t = useTranslations("Occupancy");
  const locale = useLocale();
  const text = useHeldText(zone);
  const starts = zonedInstant(days[0], "00:00", zone).getTime();
  const ends = zonedInstant(
    addDays(days[days.length - 1], 1),
    "00:00",
    zone,
  ).getTime();
  const span = (from: number, to: number) => {
    const left = Math.max(from, starts);
    const right = Math.min(to, ends);
    return {
      left: `${((left - starts) / (ends - starts)) * 100}%`,
      width: `${(Math.max(right - left, 0) / (ends - starts)) * 100}%`,
    };
  };
  const closedFor = (unit: OccupancyUnit) =>
    new Set(
      data.closures
        .filter(
          (closure) =>
            closure.location_id === null ||
            closure.location_id === unit.location_id,
        )
        .flatMap((closure) =>
          days.filter(
            (day) => day >= closure.starts_on && day <= closure.ends_on,
          ),
        ),
    );
  const columns = {
    gridTemplateColumns: `repeat(${days.length}, minmax(0, 1fr))`,
  };

  return (
    // Wider than the screen it scrolls inside its box; a keyboard can too.
    <div
      aria-label={t("gridLabel")}
      className="overflow-x-auto max-sm:hidden"
      role="region"
      tabIndex={0}
    >
      <div className="min-w-[48rem]">
        <div className="flex border-b text-xs text-muted-foreground">
          <div className="w-40 shrink-0 py-2 pr-2 font-medium">{t("unit")}</div>
          <div className="grid flex-1" style={columns}>
            {days.map((day) => (
              <div
                className={cn(
                  "py-2 text-center",
                  day === today && "font-semibold text-foreground",
                )}
                key={day}
              >
                {formatDay(day, locale, { weekday: "short" })}
                <br />
                {formatDay(day, locale, { day: "numeric", month: "numeric" })}
              </div>
            ))}
          </div>
        </div>
        {data.units.map((unit) => {
          const closed = closedFor(unit);
          const held = data.held.filter((item) => item.unit_id === unit.id);
          return (
            <div
              aria-label={unit.name}
              className="flex border-b last:border-b-0"
              key={unit.id}
              role="group"
            >
              <div className="w-40 shrink-0 py-3 pr-2 text-sm">
                <p className="font-medium wrap-anywhere">{unit.name}</p>
                {unit.group_name ? (
                  <p className="text-xs text-muted-foreground">
                    {unit.group_name}
                  </p>
                ) : null}
              </div>
              <div className="relative min-h-14 flex-1">
                <div
                  aria-hidden="true"
                  className="absolute inset-0 grid"
                  style={columns}
                >
                  {days.map((day) => (
                    <div
                      className={cn(
                        "border-l",
                        day === today && "bg-primary/5",
                        closed.has(day) && CLOSED,
                      )}
                      key={day}
                      title={closed.has(day) ? t("legendClosed") : undefined}
                    />
                  ))}
                </div>
                {held.length ? (
                  <ul aria-label={t("unitHeld", { unit: unit.name })}>
                    {held.map((item) => {
                      const label = text(item);
                      const place = span(
                        Date.parse(item.starts_at),
                        Date.parse(item.ends_at),
                      );
                      const bar = cn(
                        "absolute top-2 bottom-2 flex items-center overflow-hidden rounded-md px-1.5 text-xs whitespace-nowrap",
                        heldStyle(item),
                      );
                      return (
                        <li
                          key={`${item.kind}-${item.appointment_id ?? item.block_id}`}
                        >
                          {item.appointment_id ? (
                            <Link
                              aria-label={label}
                              className={cn(bar, "hover:opacity-90")}
                              href={dayHref(item, zone)}
                              style={place}
                              title={label}
                            >
                              <span className="truncate">{item.title}</span>
                            </Link>
                          ) : (
                            <span className={bar} style={place} title={label}>
                              <span className="sr-only">{label}</span>
                              <span aria-hidden="true" className="truncate">
                                {item.title || t("legendBlock")}
                              </span>
                            </span>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <span className="sr-only">{t("free")}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** The phone's grid: each unit with what holds it, in order. */
function Agenda({ data, zone }: { data: BookingOccupancy; zone: string }) {
  const t = useTranslations("Occupancy");
  const text = useHeldText(zone);
  return (
    <div className="space-y-4 sm:hidden">
      {data.units.map((unit) => {
        const held = data.held.filter((item) => item.unit_id === unit.id);
        return (
          <section className="space-y-1" key={unit.id}>
            <h3 className="text-sm font-semibold">{unit.name}</h3>
            {held.length ? (
              <ol className="space-y-1">
                {held.map((item) => (
                  <li
                    className={cn(
                      "rounded-md px-2 py-1.5 text-sm",
                      heldStyle(item),
                    )}
                    key={`${item.kind}-${item.appointment_id ?? item.block_id}`}
                  >
                    {item.appointment_id ? (
                      <Link
                        className="block min-h-8"
                        href={dayHref(item, zone)}
                      >
                        {text(item)}
                      </Link>
                    ) : (
                      text(item)
                    )}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-muted-foreground">{t("free")}</p>
            )}
          </section>
        );
      })}
    </div>
  );
}

function Legend() {
  const t = useTranslations("Occupancy");
  const swatch = "inline-block h-3 w-5 rounded-sm";
  // The calendar's statuses and hatch: the same meaning on both tabs.
  return (
    <ul
      aria-label={t("legend")}
      className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground"
    >
      {(["confirmed", "passed", "completed"] as const).map((status) => (
        <li key={status}>
          <StatusBadge status={status} />
        </li>
      ))}
      <li className="flex items-center gap-1.5">
        <span className={cn(swatch, BLOCK)} />
        {t("legendBlock")}
      </li>
      <li className="flex items-center gap-1.5">
        <span className={cn(swatch, "border", CLOSED)} />
        {t("legendClosed")}
      </li>
    </ul>
  );
}
