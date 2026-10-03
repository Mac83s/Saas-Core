import { expect, test } from "vitest";

import {
  formatDate,
  formatDateRange,
  formatDateTime,
  formatHours,
  formatVisit,
} from "./dates";

const ZONE = "Europe/Warsaw";
const JOIN = "⁠";

test("a day key is the day it names, in any viewer's zone", () => {
  expect(formatDate("2026-09-30", "pl")).toBe("30 wrz 2026");
  expect(formatDate("2026-09-30", "en")).toBe("Sep 30, 2026");
});

test("a moment has the day and a 24-hour time", () => {
  expect(formatDateTime("2026-09-30T12:00:00Z", "pl", ZONE)).toBe(
    "30 wrz 2026, 14:00",
  );
});

test("a range of hours never breaks at its dash", () => {
  expect(
    formatHours("2026-10-01T06:00:00Z", "2026-10-01T07:00:00Z", "pl", ZONE),
  ).toBe(`08:00${JOIN}–${JOIN}09:00`);
});

test("a visit is its weekday, day and hours", () => {
  expect(
    formatVisit("2026-10-01T06:00:00Z", "2026-10-01T07:00:00Z", "pl", ZONE),
  ).toBe(`czw., 1.10, 08:00${JOIN}–${JOIN}09:00`);
});

test("a span of days writes the month once", () => {
  expect(formatDateRange("2026-10-01", "2026-10-02", "pl")).toBe(
    `1${JOIN}–${JOIN}2 paź 2026`,
  );
});

test("a span of dates with words keeps hard spaces around the dash", () => {
  expect(formatDateRange("2026-09-28", "2026-10-04", "pl")).toBe(
    "28 wrz\u00a0–\u00a04 paź 2026",
  );
});
