"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { addDays, addMonths, formatDay } from "./calendar-time";

/** The words of the calendar, from the catalogue of whoever shows it: the
 *  booking form's messages, or the texts of a company's own site. */
export type StayDateLabels = {
  previousMonth: string;
  nextMonth: string;
  /** What is asked for now: the first day, then the last one. */
  pickStart: string;
  pickEnd: string;
  /** The chosen days, said after their dates. */
  start: string;
  end: string;
  /** A day a stay can begin on, and one it cannot. */
  free: string;
  unavailable: string;
  clear: string;
  loading: string;
  loadError: string;
  noDays: string;
  /** „3 noce”, „2 dni”. */
  length: (count: number) => string;
};

type Loaded = string[] | "error";

/** A question the server did not answer — too many at once, a lost
 *  connection — is put again by itself so many times before it is said to
 *  have failed. */
const RETRIES = 3;

/** Monday first, as the rest of the product's calendars. */
function weekdays(locale: string): { short: string; long: string }[] {
  return Array.from({ length: 7 }, (_, index) => {
    const day = addDays("2024-01-01", index);
    return {
      short: formatDay(day, locale, { weekday: "short" }),
      long: formatDay(day, locale, { weekday: "long" }),
    };
  });
}

function daysOf(month: string): string[] {
  const next = addMonths(month, 1);
  const days: string[] = [];
  for (let day = month; day < next; day = addDays(day, 1)) days.push(day);
  return days;
}

/** Nights between two days, or days from the first to the last one. */
export function stayLength(
  start: string,
  end: string,
  unit: "night" | "day",
): number {
  return (
    Math.round(
      (Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) /
        86400000,
    ) + (unit === "day" ? 1 : 0)
  );
}

/**
 * The days of a stay picked in a month grid (ADR-072, slice 5d): the days a
 * stay can begin on are the server's (`loadStarts`, a month at a time — one
 * search never spans more than the form's 92 days), and so are the days a
 * stay from the chosen one can end on (`loadEnds`). The grid only asks and
 * marks; it never works out what is free.
 */
export function StayDatePicker({
  end,
  invalid = false,
  labels,
  lastDay,
  loadEnds,
  loadStarts,
  locale,
  months = 1,
  onChange,
  retryAfterMs = 5000,
  searchKey,
  start,
  today,
  unit,
}: {
  end: string;
  /** Nothing chosen where a choice is required: said by the caller. */
  invalid?: boolean;
  labels: StayDateLabels;
  /** The last day a stay can begin on. */
  lastDay: string;
  loadEnds: (start: string) => Promise<string[]>;
  loadStarts: (from: string, to: string) => Promise<string[]>;
  locale: string;
  /** Months side by side on a wide screen; a narrow one shows the first. */
  months?: 1 | 2;
  onChange: (start: string, end: string) => void;
  /** How long a question that failed waits before it is put again. */
  retryAfterMs?: number;
  /** What is searched — the offer and what is booked of it. Another one
   *  forgets every day loaded so far. */
  searchKey: string;
  start: string;
  /** The company's today. */
  today: string;
  unit: "night" | "day";
}) {
  const firstMonth = `${today.slice(0, 7)}-01`;
  const lastMonth = `${lastDay.slice(0, 7)}-01`;
  const [month, setMonth] = useState(() =>
    start ? `${start.slice(0, 7)}-01` : firstMonth,
  );
  // The days found, by search and month; an answer for another search is
  // never shown.
  const [found, setFound] = useState<{
    key: string;
    months: Record<string, Loaded>;
  }>({ key: searchKey, months: {} });
  const starts = useMemo(
    () => (found.key === searchKey ? found.months : {}),
    [found, searchKey],
  );
  const [ends, setEnds] = useState<{
    key: string;
    start: string;
    days: Loaded;
  }>();
  const allowed =
    ends && ends.key === searchKey && ends.start === start
      ? ends.days
      : undefined;
  const shown = useMemo(
    () =>
      Array.from({ length: months }, (_, index) =>
        addMonths(month, index),
      ).filter((item) => item <= lastMonth),
    [lastMonth, month, months],
  );
  const missing = shown.filter((item) => starts[item] === undefined).join(",");

  // Counts the questions put again after a failure, and makes the next one.
  const tries = useRef(0);
  const [again, setAgain] = useState(0);
  useEffect(() => {
    if (!missing || !searchKey) return;
    let current = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const asked = missing.split(",");
    // One question for the months shown — neighbours, so never more than the
    // form's window — from today, to the form's last day.
    const from = [asked[0]!, today].sort()[1]!;
    const to = [addDays(addMonths(asked.at(-1)!, 1), -1), lastDay].sort()[0]!;
    const fill = (days: Loaded) =>
      setFound((before) => ({
        key: searchKey,
        months: {
          ...(before.key === searchKey ? before.months : {}),
          ...Object.fromEntries(
            asked.map((item) => [
              item,
              days === "error"
                ? days
                : days.filter((day) => day.startsWith(item.slice(0, 7))),
            ]),
          ),
        },
      }));
    (from > to ? Promise.resolve<string[]>([]) : loadStarts(from, to)).then(
      (days) => {
        if (!current) return;
        tries.current = 0;
        fill(days);
      },
      () => {
        if (!current) return;
        if (tries.current >= RETRIES) return fill("error");
        tries.current += 1;
        timer = setTimeout(() => setAgain((count) => count + 1), retryAfterMs);
      },
    );
    return () => {
      current = false;
      clearTimeout(timer);
    };
    // `loadStarts` belongs to `searchKey`: the same search must not ask twice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [again, lastDay, missing, searchKey, today]);
  useEffect(() => {
    if (!start || !searchKey) return;
    let current = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    loadEnds(start).then(
      (days) => {
        if (!current) return;
        tries.current = 0;
        setEnds({ key: searchKey, start, days });
      },
      () => {
        if (!current) return;
        if (tries.current >= RETRIES)
          return setEnds({ key: searchKey, start, days: "error" });
        tries.current += 1;
        timer = setTimeout(() => setAgain((count) => count + 1), retryAfterMs);
      },
    );
    return () => {
      current = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [again, searchKey, start]);

  const names = useMemo(() => weekdays(locale), [locale]);
  const free = (day: string) => {
    const days = starts[`${day.slice(0, 7)}-01`];
    return Array.isArray(days) && days.includes(day);
  };
  const closes = (day: string) =>
    Boolean(start) &&
    day > start &&
    Array.isArray(allowed) &&
    allowed.includes(day);
  function pick(day: string) {
    if (day === start) onChange("", "");
    else if (closes(day)) onChange(start, day);
    else onChange(day, "");
  }
  const loading =
    shown.some((item) => starts[item] === undefined) ||
    (Boolean(start) && allowed === undefined);
  const failed =
    shown.some((item) => starts[item] === "error") || allowed === "error";
  const nothing =
    !start &&
    !loading &&
    !failed &&
    shown.every((item) => (starts[item] as string[]).length === 0);
  const long = (day: string) =>
    formatDay(day, locale, {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
    });
  const short = (day: string) =>
    formatDay(day, locale, { day: "numeric", month: "long" });

  return (
    <div className="stay-calendar" data-invalid={invalid || undefined}>
      <div className="stay-calendar__bar">
        <button
          aria-label={labels.previousMonth}
          className="stay-calendar__move"
          disabled={month <= firstMonth}
          onClick={() => setMonth(addMonths(month, -1))}
          type="button"
        >
          <span aria-hidden="true">‹</span>
        </button>
        <button
          aria-label={labels.nextMonth}
          className="stay-calendar__move"
          disabled={addMonths(month, 1) > lastMonth}
          onClick={() => setMonth(addMonths(month, 1))}
          type="button"
        >
          <span aria-hidden="true">›</span>
        </button>
      </div>
      <div className="stay-calendar__months" data-months={shown.length}>
        {shown.map((item) => {
          const title = formatDay(item, locale, {
            month: "long",
            year: "numeric",
          });
          // Monday first: the blanks before the month's first day.
          const blanks = (new Date(`${item}T00:00:00Z`).getUTCDay() + 6) % 7;
          return (
            <div
              aria-label={title}
              className="stay-calendar__month"
              key={item}
              role="group"
            >
              <p aria-hidden="true" className="stay-calendar__title">
                {title}
              </p>
              <div aria-hidden="true" className="stay-calendar__week">
                {names.map((name) => (
                  <span key={name.long} title={name.long}>
                    {name.short}
                  </span>
                ))}
              </div>
              <div className="stay-calendar__days">
                {Array.from({ length: blanks }, (_, index) => (
                  <span key={`blank-${index}`} />
                ))}
                {daysOf(item).map((day) => {
                  const first = day === start;
                  const last = day === end;
                  const closing = closes(day);
                  const opening = free(day);
                  const between =
                    Boolean(start && end) && day > start && day < end;
                  const state = first
                    ? labels.start
                    : last
                      ? labels.end
                      : closing
                        ? `${labels.end}, ${labels.length(stayLength(start, day, unit))}`
                        : opening
                          ? labels.free
                          : labels.unavailable;
                  return (
                    <button
                      aria-label={`${long(day)}, ${state}`}
                      aria-pressed={first || last}
                      className="stay-calendar__day"
                      data-state={
                        first || last
                          ? "chosen"
                          : between
                            ? "between"
                            : closing
                              ? "closing"
                              : opening
                                ? "free"
                                : undefined
                      }
                      disabled={!first && !closing && !opening}
                      key={day}
                      onClick={() => pick(day)}
                      type="button"
                    >
                      {Number(day.slice(8))}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
      <div className="stay-calendar__foot">
        <p aria-live="polite" className="stay-calendar__status">
          {failed
            ? labels.loadError
            : loading
              ? labels.loading
              : start && end
                ? `${short(start)} – ${short(end)} · ${labels.length(stayLength(start, end, unit))}`
                : start
                  ? `${short(start)} · ${labels.pickEnd}`
                  : nothing
                    ? labels.noDays
                    : labels.pickStart}
        </p>
        {start ? (
          <button
            className="stay-calendar__clear"
            onClick={() => onChange("", "")}
            type="button"
          >
            {labels.clear}
          </button>
        ) : null}
      </div>
      <p aria-hidden="true" className="stay-calendar__legend">
        <span data-state="free">{labels.free}</span>
        <span>{labels.unavailable}</span>
      </p>
    </div>
  );
}
