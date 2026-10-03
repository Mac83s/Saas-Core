import { useSyncExternalStore } from "react";

/**
 * One way to write a date in the panel (UX-011): a day is „30 wrz 2026”, a
 * moment „30 wrz 2026, 14:00”, a visit „czw., 1.10, 08:00–09:00”. A range of
 * hours never breaks at its dash: „08:00–” and „09:00” on two lines read as two
 * times.
 *
 * A day key ("2026-09-30": an expiry, a calendar day) is read where it was
 * written; an instant in `timeZone`, the viewer's when none is given.
 */

const formats = new Map<string, Intl.DateTimeFormat>();

/** A cached formatter: a month of visits formats hundreds of dates. */
export function dateFormat(
  locale: string,
  options: Intl.DateTimeFormatOptions,
): Intl.DateTimeFormat {
  const key = locale + JSON.stringify(options);
  let format = formats.get(key);
  if (!format) {
    format = new Intl.DateTimeFormat(locale, options);
    formats.set(key, format);
  }
  return format;
}

const DAY_KEY = /^\d{4}-\d{2}-\d{2}$/;
/** U+2060 glues the dash to both times: no line break inside a range. */
const JOIN = "⁠";

function instant(value: Date | string): {
  date: Date;
  timeZone?: string;
} {
  return typeof value === "string" && DAY_KEY.test(value)
    ? { date: new Date(`${value}T12:00:00Z`), timeZone: "UTC" }
    : { date: new Date(value) };
}

const DAY: Intl.DateTimeFormatOptions = {
  day: "numeric",
  month: "short",
  year: "numeric",
};
const TIME: Intl.DateTimeFormatOptions = {
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
};

/** „30 wrz 2026”. */
export function formatDate(
  value: Date | string,
  locale: string,
  timeZone?: string,
): string {
  const { date, timeZone: own } = instant(value);
  return dateFormat(locale, { ...DAY, timeZone: own ?? timeZone }).format(date);
}

/** „30 wrz 2026, 14:00”. */
export function formatDateTime(
  value: Date | string,
  locale: string,
  timeZone?: string,
): string {
  return dateFormat(locale, { ...DAY, ...TIME, timeZone }).format(
    new Date(value),
  );
}

/** „08:00–09:00”, unbreakable. */
export function formatHours(
  start: Date | string,
  end: Date | string,
  locale: string,
  timeZone?: string,
): string {
  return glue(
    dateFormat(locale, { ...TIME, timeZone }).formatRange(
      new Date(start),
      new Date(end),
    ),
  );
}

/** „czw., 1.10, 08:00–09:00”: a visit's day and its hours. */
export function formatVisit(
  start: Date | string,
  end: Date | string,
  locale: string,
  timeZone?: string,
): string {
  const day = dateFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "numeric",
    timeZone,
  }).format(new Date(start));
  return `${day}, ${formatHours(start, end, locale, timeZone)}`;
}

/** „1–2 paź 2026” for two day keys or instants, unbreakable at the dash. */
export function formatDateRange(
  from: Date | string,
  to: Date | string,
  locale: string,
  timeZone?: string,
): string {
  const start = instant(from);
  const end = instant(to);
  return glue(
    dateFormat(locale, {
      ...DAY,
      timeZone: start.timeZone ?? timeZone,
    }).formatRange(start.date, end.date),
  );
}

/**
 * „czas środkowoeuropejski, UTC+02:00” — a zone the way people know it,
 * never „Europe/Warsaw” (UX-019).
 */
export function formatZone(timeZone: string, locale: string): string {
  const part = (timeZoneName: "longGeneric" | "longOffset") =>
    dateFormat(locale, { timeZone, timeZoneName })
      .formatToParts(new Date())
      .find((item) => item.type === "timeZoneName")?.value;
  const offset = part("longOffset")?.replace(/^GMT/, "UTC");
  return [part("longGeneric"), offset].filter(Boolean).join(", ");
}

function viewerZone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/**
 * Whether the viewer's browser is in another zone than `timeZone`: only then
 * is the zone worth a word. The server render assumes the same zone.
 */
export function useOtherZone(timeZone: string): boolean {
  return useSyncExternalStore(
    () => () => undefined,
    () => viewerZone() !== timeZone,
    () => false,
  );
}

/**
 * One dash, written the same in Node and in the browser. Between times or
 * numbers it is tight („08:00–09:00”, „1–2 paź”); between dates with words it
 * keeps hard spaces („28 wrz – 4 paź 2026”). Neither ever breaks a line.
 */
function glue(range: string): string {
  const [left = ""] = range.split(/\s*[–-]\s*/);
  const dash = /\s/.test(left.trim()) ? "\u00a0–\u00a0" : `${JOIN}–${JOIN}`;
  return range.replace(/\s*[–-]\s*/, dash);
}
