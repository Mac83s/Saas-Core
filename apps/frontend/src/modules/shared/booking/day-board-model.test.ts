import { expect, test } from "vitest";

import type { BookingAppointment, Person } from "@saas-core/api-client";

import {
  boardRange,
  boardRows,
  dayBounds,
  dayState,
  freeWindows,
  hourTicks,
  otherBusy,
  visitsOf,
} from "./day-board-model";

const ZONE = "Europe/Warsaw";
const at = (iso: string) => Date.parse(iso);
const interval = (from: string, to: string) => ({
  starts_at: from,
  ends_at: to,
});

const visit = (
  fields: Partial<BookingAppointment> & { id: string },
): BookingAppointment => ({
  starts_at: "2026-08-19T11:00:00Z",
  ends_at: "2026-08-19T12:00:00Z",
  timezone: ZONE,
  service_name: "Consultation",
  status: "confirmed",
  customer_name: "Jan",
  staff_id: "alex",
  staff_name: "Alex",
  staff_membership_id: null,
  location_name: "Centrum",
  place: null,
  appointment_kind: "",
  flags: [],
  customer_phone: null,
  customer_email: null,
  resource_name: null,
  crew: [{ staff_id: "alex", name: "Alex", membership_id: null, lead: true }],
  staff_required: 1,
  needs_assignment: false,
  auto_assigned: false,
  crew_version: 1,
  queue_reason: "",
  queued_at: null,
  requested_team: null,
  requested_staff_id: null,
  customer_notes: "",
  ...fields,
});

const person = (id: string, fields: Partial<Person> = {}): Person => ({
  id,
  name: id,
  public_slug: id,
  membership_id: null,
  invitation_id: null,
  phone: null,
  active: true,
  service_ids: ["s1"],
  has_hours: true,
  team_ids: [],
  public_name: null,
  created_at: "2026-01-01T00:00:00Z",
  ...fields,
});

test("the axis covers the day's hours and visits in whole hours, at least 08–16", () => {
  // 07:00–15:00 hours and a visit until 16:30 in Warsaw (UTC+2 in August).
  const range = boardRange("2026-08-19", ZONE, [
    { from: at("2026-08-19T05:00:00Z"), to: at("2026-08-19T13:00:00Z") },
    { from: at("2026-08-19T14:00:00Z"), to: at("2026-08-19T14:30:00Z") },
  ]);
  expect(range).toEqual({
    from: at("2026-08-19T05:00:00Z"),
    to: at("2026-08-19T15:00:00Z"),
  });
  expect(boardRange("2026-08-19", ZONE, [])).toEqual({
    from: at("2026-08-19T06:00:00Z"),
    to: at("2026-08-19T14:00:00Z"),
  });
});

test("a day with the clock change has 25 or 23 hours and its hours say so", () => {
  const autumn = dayBounds("2026-10-25", ZONE);
  expect((autumn.to - autumn.from) / 3_600_000).toBe(25);
  const spring = dayBounds("2026-03-29", ZONE);
  expect((spring.to - spring.from) / 3_600_000).toBe(23);

  // 01:00–04:00 local on either day.
  expect(
    hourTicks(
      { from: at("2026-10-24T23:00:00Z"), to: at("2026-10-25T03:00:00Z") },
      ZONE,
    ).map((tick) => tick.label),
  ).toEqual(["01:00", "02:00", "02:00", "03:00", "04:00"]);
  expect(
    hourTicks(
      { from: at("2026-03-29T00:00:00Z"), to: at("2026-03-29T02:00:00Z") },
      ZONE,
    ).map((tick) => tick.label),
  ).toEqual(["01:00", "03:00", "04:00"]);
});

test("free windows are the hours less visits, absences and the past, long enough to book", () => {
  const day = {
    staff_id: "alex",
    // 08:00–16:00 local, a visit 10:00–11:00, away 13:00–14:00.
    works: [interval("2026-08-19T06:00:00Z", "2026-08-19T14:00:00Z")],
    busy: [interval("2026-08-19T08:00:00Z", "2026-08-19T09:00:00Z")],
    time_off: [
      {
        ...interval("2026-08-19T11:00:00Z", "2026-08-19T12:00:00Z"),
        reason: null,
      },
    ],
  };
  // 09:07: the next quarter hour is the first bookable start.
  const now = at("2026-08-19T07:07:00Z");
  expect(freeWindows(day, now, 30)).toEqual([
    { from: at("2026-08-19T07:15:00Z"), to: at("2026-08-19T08:00:00Z") },
    { from: at("2026-08-19T09:00:00Z"), to: at("2026-08-19T11:00:00Z") },
    { from: at("2026-08-19T12:00:00Z"), to: at("2026-08-19T14:00:00Z") },
  ]);
  // Forty-five minutes cannot take an hour's service.
  expect(freeWindows(day, now, 60)).toHaveLength(2);
  // A day gone by has nothing left to plan.
  expect(freeWindows(day, at("2026-08-20T00:00:00Z"), 30)).toEqual([]);
});

test("a person's visits: canceled ones and a vacancy they lead in name only are not theirs", () => {
  const items = [
    visit({ id: "later", starts_at: "2026-08-19T12:00:00Z" }),
    visit({ id: "first", starts_at: "2026-08-19T08:00:00Z" }),
    visit({ id: "canceled", status: "canceled" }),
    visit({ id: "vacancy", needs_assignment: true, crew: [] }),
    visit({
      id: "helper",
      staff_id: "bea",
      crew: [
        { staff_id: "bea", name: "Bea", membership_id: null, lead: true },
        { staff_id: "alex", name: "Alex", membership_id: null, lead: false },
      ],
    }),
  ];
  expect(visitsOf(items, "alex").map((item) => item.id)).toEqual([
    "first",
    "helper",
    "later",
  ]);
});

test("time held with no visit behind it is its own block; a visit's buffer is not", () => {
  const day = {
    staff_id: "alex",
    works: [],
    time_off: [],
    busy: [
      interval("2026-08-19T08:50:00Z", "2026-08-19T10:10:00Z"),
      interval("2026-08-19T12:00:00Z", "2026-08-19T13:00:00Z"),
    ],
  };
  expect(
    otherBusy(day, [
      { from: at("2026-08-19T09:00:00Z"), to: at("2026-08-19T10:00:00Z") },
    ]),
  ).toEqual([
    { from: at("2026-08-19T12:00:00Z"), to: at("2026-08-19T13:00:00Z") },
  ]);
});

test("the board's people, the filters and another day in a few words", () => {
  const people = [
    person("alex", { team_ids: ["north"] }),
    person("bea"),
    person("office", { service_ids: [], has_hours: false }),
    person("helper", { service_ids: [], has_hours: false }),
  ];
  const day = {
    date: "2026-08-19",
    timezone: ZONE,
    items: [
      {
        staff_id: "alex",
        works: [interval("2026-08-19T06:00:00Z", "2026-08-19T14:00:00Z")],
        busy: [],
        time_off: [],
      },
      { staff_id: "bea", works: [], busy: [], time_off: [] },
      { staff_id: "office", works: [], busy: [], time_off: [] },
      {
        staff_id: "helper",
        works: [],
        busy: [interval("2026-08-19T08:00:00Z", "2026-08-19T09:00:00Z")],
        time_off: [],
      },
    ],
  };
  const rows = (scheduled: boolean, only: Set<string> | null = null) =>
    boardRows({ people, day, appointments: [], scheduled, only }).map(
      (row) => row.staffId,
    );
  expect(rows(false)).toEqual(["alex", "bea", "helper"]);
  expect(rows(true)).toEqual(["alex"]);
  expect(rows(false, new Set(["bea"]))).toEqual(["bea"]);

  expect(dayState(day.items[0])).toEqual({
    kind: "works",
    hours: [
      { from: at("2026-08-19T06:00:00Z"), to: at("2026-08-19T14:00:00Z") },
    ],
  });
  expect(dayState(day.items[1])).toEqual({ kind: "off" });
  expect(
    dayState({
      ...day.items[0],
      time_off: [
        {
          ...interval("2026-08-18T22:00:00Z", "2026-08-19T22:00:00Z"),
          reason: null,
        },
      ],
    }),
  ).toEqual({ kind: "away" });
});
