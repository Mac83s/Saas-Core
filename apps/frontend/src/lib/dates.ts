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

function glue(range: string): string {
  return range.replace(/\s*[–-]\s*/, `${JOIN}–${JOIN}`);
}
