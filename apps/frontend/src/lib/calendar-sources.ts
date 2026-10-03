import { farmVisitsSource } from "../modules/shared/farms/calendar-source";

/**
 * Something on the calendar that is not the company's own booking: a company's
 * visit to a farm, read from the keeper's register (UX-078). Read-only — it is
 * changed where it lives, so the calendar never offers to move or cancel it.
 */
export type OutsideEntry = {
  id: string;
  /** The moment, when one is known; else `day` says only which day. */
  at: string | null;
  day: string | null;
  title: string;
  detail: string;
  status: "planned" | "done" | "canceled";
  /** Where it is read in full, if anywhere. */
  href?: string;
};

/**
 * A source of such entries, shown by whoever its gates let through — the same
 * gates as a menu entry. Core modules list theirs here; nothing registers at
 * run time, so a product adds none by accident.
 */
export type CalendarSource = {
  key: string;
  /** The message key of its legend entry, e.g. "Farms.calendarVisit". */
  labelKey: string;
  module?: string;
  permission?: string;
  organizationTypes?: readonly string[];
  /** Local days, both included. */
  load: (from: string, to: string) => Promise<OutsideEntry[]>;
};

export const CALENDAR_SOURCES: readonly CalendarSource[] = [farmVisitsSource];
