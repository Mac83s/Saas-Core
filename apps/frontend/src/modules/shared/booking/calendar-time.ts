/**
 * Calendar days are "YYYY-MM-DD" keys in the organization's zone: an
 * appointment is an instant (UTC), but the day it belongs to is the
 * business's, not the viewer's browser's (ADR-030).
 */

const formats = new Map<string, Intl.DateTimeFormat>();

/** A cached formatter: a month view formats hundreds of dates per render. */
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

/** The wall-clock day and time ("HH:mm") of an instant in `timeZone`. */
export function wallClock(
  instant: Date | string,
  timeZone: string,
): { day: string; time: string } {
  const parts = Object.fromEntries(
    dateFormat("en-US", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(new Date(instant))
      .map((part) => [part.type, part.value]),
  );
  return {
    day: `${parts.year}-${parts.month}-${parts.day}`,
    time: `${parts.hour}:${parts.minute}`,
  };
}

/** The instant that a wall-clock day and time in `timeZone` stand for. */
export function zonedInstant(day: string, time: string, timeZone: string) {
  const wall = Date.parse(`${day}T${time}:00Z`);
  const offset = (instant: number) => {
    const local = wallClock(new Date(instant), timeZone);
    return Date.parse(`${local.day}T${local.time}:00Z`) - instant;
  };
  // The second pass corrects a guess that landed on the other side of a DST
  // change from the answer.
  return new Date(wall - offset(wall - offset(wall)));
}

export function addDays(day: string, days: number): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** The first day of the month `months` away from the day's month. */
export function addMonths(day: string, months: number): string {
  const date = new Date(`${day.slice(0, 7)}-01T00:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() + months);
  return date.toISOString().slice(0, 10);
}

/** Monday of the day's week. */
// ponytail: Monday first for every locale; Intl.Locale weekInfo when a
// product sells where weeks start on Sunday.
export function weekStart(day: string): string {
  return addDays(day, -((new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7));
}

/** Formats a day key without the viewer's zone moving it to another day. */
export function formatDay(
  day: string,
  locale: string,
  options: Intl.DateTimeFormatOptions,
): string {
  return dateFormat(locale, { ...options, timeZone: "UTC" }).format(
    new Date(`${day}T12:00:00Z`),
  );
}

/** "Thu, August 20, 10:00 – 10:30 AM" in the organization's zone. */
export function formatWhen(
  appointment: { starts_at: string; ends_at: string },
  locale: string,
  timeZone: string,
): string {
  return dateFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  }).formatRange(
    new Date(appointment.starts_at),
    new Date(appointment.ends_at),
  );
}

/** "September 14 – 20, 2026" for a span of day keys. */
export function formatDayRange(from: string, to: string, locale: string) {
  return dateFormat(locale, {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).formatRange(new Date(`${from}T12:00:00Z`), new Date(`${to}T12:00:00Z`));
}
