import type {
  BookingAppointment,
  PeopleDay,
  Person,
} from "@saas-core/api-client";

import { addDays, wallClock, zonedInstant } from "./calendar-time";

/**
 * The day board's arithmetic (plan: phase 4, board 10), apart from React so
 * the awkward days — 23 and 25 hours long — are tested on their own.
 * Everything is an instant in milliseconds; the organization's zone only
 * names them.
 */

export type Span = { from: number; to: number };
export type PersonDay = PeopleDay["items"][number];

const HOUR = 3_600_000;
const MINUTE = 60_000;

const span = (item: { starts_at: string; ends_at: string }): Span => ({
  from: Date.parse(item.starts_at),
  to: Date.parse(item.ends_at),
});

/** Overlapping or touching spans as one; sorted. */
export function merge(items: Span[]): Span[] {
  const out: Span[] = [];
  for (const item of [...items].sort((a, b) => a.from - b.from)) {
    const last = out.at(-1);
    if (last && item.from <= last.to) last.to = Math.max(last.to, item.to);
    else out.push({ ...item });
  }
  return out;
}

/** The local day as instants: 23, 24 or 25 hours. */
export function dayBounds(day: string, zone: string): Span {
  return {
    from: zonedInstant(day, "00:00", zone).getTime(),
    to: zonedInstant(addDays(day, 1), "00:00", zone).getTime(),
  };
}

/** Back to the start of the local hour; zones with half-hour offsets too. */
function hourFloor(at: number, zone: string): number {
  const minutes = Number(wallClock(new Date(at), zone).time.slice(3));
  return at - (at % MINUTE) - minutes * MINUTE;
}

/**
 * What the axis covers: the earliest start to the latest end of the day's
 * hours, visits and absences, in whole hours, at least 08–16 — a board of
 * one early visit would otherwise be an hour wide.
 */
export function boardRange(day: string, zone: string, spans: Span[]): Span {
  const bounds = dayBounds(day, zone);
  const clip = (at: number) => Math.min(Math.max(at, bounds.from), bounds.to);
  let from = zonedInstant(day, "08:00", zone).getTime();
  let to = zonedInstant(day, "16:00", zone).getTime();
  for (const item of spans) {
    if (item.to <= bounds.from || item.from >= bounds.to) continue;
    from = Math.min(from, clip(item.from));
    to = Math.max(to, clip(item.to));
  }
  from = hourFloor(from, zone);
  const end = hourFloor(to, zone);
  return { from, to: Math.min(end === to ? to : end + HOUR, bounds.to) };
}

/** One mark per full hour: an autumn day shows 02:00 twice, spring skips it. */
export function hourTicks(range: Span, zone: string) {
  const ticks: { at: number; label: string }[] = [];
  for (let at = range.from; at <= range.to; at += HOUR)
    ticks.push({ at, label: wallClock(new Date(at), zone).time });
  return ticks;
}

/** Where an instant falls on the axis, 0–100. */
export function place(at: number, range: Span): number {
  const share = (at - range.from) / (range.to - range.from);
  return Math.min(Math.max(share, 0), 1) * 100;
}

/** On the visit as the calendar counts it: the lead unless it waits, or crew. */
export function onVisit(item: BookingAppointment, staffId: string): boolean {
  return (
    (item.staff_id === staffId && !item.needs_assignment) ||
    item.crew.some((person) => person.staff_id === staffId)
  );
}

/** The person's visits that take time: a canceled one takes none. */
export function visitsOf(
  appointments: BookingAppointment[],
  staffId: string,
): BookingAppointment[] {
  return appointments
    .filter((item) => item.status !== "canceled" && onVisit(item, staffId))
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at));
}

/**
 * Time the calendar holds for somebody with no visit the viewer sees behind
 * it — a product's "join", or a visit outside the filters. Buffers around a
 * visit are part of that visit, not a block of their own.
 */
export function otherBusy(
  person: PersonDay | undefined,
  visits: Span[],
): Span[] {
  return merge((person?.busy ?? []).map(span)).filter(
    (block) =>
      !visits.some((visit) => visit.from < block.to && visit.to > block.from),
  );
}

/**
 * Free windows inside the person's hours: not busy, not away, not past, and
 * long enough for the shortest service they do. Anything shorter could not be
 * booked, so it is not offered.
 */
export function freeWindows(
  person: PersonDay | undefined,
  now: number,
  minutes: number,
): Span[] {
  if (!person) return [];
  const blocked = merge([
    ...person.busy.map(span),
    ...person.time_off.map(span),
  ]);
  const out: Span[] = [];
  for (const work of merge(person.works.map(span))) {
    // A start in the past cannot be booked; the next quarter hour can.
    let start = Math.max(
      work.from,
      Math.ceil(now / (15 * MINUTE)) * 15 * MINUTE,
    );
    for (const block of blocked) {
      if (block.to <= start || block.from >= work.to) continue;
      if (block.from > start) out.push({ from: start, to: block.from });
      start = Math.max(start, block.to);
    }
    if (start < work.to) out.push({ from: start, to: work.to });
  }
  return out.filter((item) => item.to - item.from >= minutes * MINUTE);
}

/**
 * Another day than today in a few words: when the person works, away for the
 * whole of it, or not working at all.
 */
export function dayState(
  person: PersonDay | undefined,
): { kind: "works"; hours: Span[] } | { kind: "away" } | { kind: "off" } {
  const hours = merge((person?.works ?? []).map(span));
  if (!hours.length) return { kind: "off" };
  const away = merge((person?.time_off ?? []).map(span));
  const covered = hours.every((work) =>
    away.some((item) => item.from <= work.from && item.to >= work.to),
  );
  return covered ? { kind: "away" } : { kind: "works", hours };
}

/** The shortest visit the person could take: their services' durations. */
export function shortestService(
  person: Person | undefined,
  services: { id: string; duration_minutes: number }[],
): number {
  const own = services.filter((item) => person?.service_ids.includes(item.id));
  const durations = (own.length ? own : services).map(
    (item) => item.duration_minutes,
  );
  return durations.length ? Math.min(...durations) : 30;
}

export type BoardRow = {
  staffId: string;
  name: string;
  person?: Person;
  day?: PersonDay;
  visits: BookingAppointment[];
};

/**
 * The board's people: those who take visits, and anybody the day holds
 * something for. `scheduled` keeps only those with hours that day.
 */
export function boardRows({
  people,
  day,
  appointments,
  scheduled,
  only,
}: {
  people: Person[];
  day: PeopleDay | undefined;
  appointments: BookingAppointment[];
  scheduled: boolean;
  /** A team's or one person's rows; null: everybody. */
  only: Set<string> | null;
}): BoardRow[] {
  const byId = new Map(people.map((person) => [person.id, person]));
  return (day?.items ?? [])
    .map((item) => {
      const person = byId.get(item.staff_id);
      return {
        staffId: item.staff_id,
        name: person?.name ?? "",
        person,
        day: item,
        visits: visitsOf(appointments, item.staff_id),
      };
    })
    .filter(
      (row) =>
        row.person &&
        (!only || only.has(row.staffId)) &&
        (scheduled
          ? row.day.works.length > 0
          : (row.person.service_ids.length > 0 && row.person.has_hours) ||
            row.visits.length > 0 ||
            row.day.busy.length > 0 ||
            row.day.time_off.length > 0),
    );
}
