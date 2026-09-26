import { expect, test } from "vitest";

import type {
  InvitationSummary,
  MembershipSummary,
  PeopleDay,
  Person,
} from "@saas-core/api-client";

import { managesTeam } from "../../../core/organizations/role-groups";
import { filterPeople, hoursSummary, joinPeople, todayState } from "./people";

const member = (over: Partial<MembershipSummary> = {}): MembershipSummary => ({
  id: "m-1",
  user_id: "u-1",
  email: "jan@example.com",
  first_name: "Jan",
  last_name: "Wójcik",
  role: "owner",
  status: "active",
  joined_at: "2025-03-01T08:00:00Z",
  revoked_at: null,
  ...over,
});

const invitation = (
  over: Partial<InvitationSummary> = {},
): InvitationSummary => ({
  id: "i-1",
  email: "kamil@example.com",
  role: "trimmer",
  status: "pending",
  expires_at: "2026-10-01T08:00:00Z",
  created_at: "2026-09-24T08:00:00Z",
  ...over,
});

const person = (over: Partial<Person> = {}): Person => ({
  id: "s-1",
  name: "Marcin Kowalski",
  public_slug: "marcin",
  membership_id: null,
  invitation_id: null,
  phone: "601 234 567",
  active: true,
  service_ids: ["svc"],
  has_hours: true,
  created_at: "2025-03-01T08:00:00Z",
  ...over,
});

test("one row per person: an entry with its account, an invitation, a bare account", () => {
  const rows = joinPeople({
    members: [
      member(),
      member({ id: "m-2", user_id: "u-2", email: "marcin@example.com" }),
    ],
    invitations: [invitation()],
    staff: [
      person({ membership_id: "m-2" }),
      person({
        id: "s-2",
        name: "Kamil Duda",
        phone: null,
        invitation_id: "i-1",
        service_ids: [],
      }),
      person({ id: "s-3", name: "Krzysztof Nowak" }),
    ],
    userId: "u-1",
  });
  expect(
    rows.map((row) => [row.name, row.account, row.cardId, row.self]),
  ).toEqual([
    ["Marcin Kowalski", "active", "s-1", false],
    ["Kamil Duda", "invited", "s-2", false],
    ["Krzysztof Nowak", "none", "s-3", false],
    ["Jan Wójcik", "active", "m-1", true],
  ]);
  // The invitation is Kamil's row, not a second one.
  expect(rows.filter((row) => row.invitation)).toHaveLength(1);
  expect(rows.map((row) => row.takesVisits)).toEqual([
    true,
    false,
    true,
    false,
  ]);
});

test("a resent invitation is found by its e-mail; the old one stays out", () => {
  const rows = joinPeople({
    members: [],
    invitations: [
      invitation({ id: "i-1", status: "revoked" }),
      invitation({ id: "i-2", created_at: "2026-09-25T08:00:00Z" }),
    ],
    staff: [person({ invitation_id: "i-1", name: "Kamil Duda" })],
  });
  expect(rows).toHaveLength(1);
  expect(rows[0].invitation?.id).toBe("i-2");
  expect(rows[0].account).toBe("invited");
});

test("nobody drops off: former people are rows, filtered apart from the account", () => {
  const rows = joinPeople({
    members: [
      member(),
      member({
        id: "m-9",
        user_id: "u-9",
        email: "byly@example.com",
        first_name: "",
        last_name: "",
        status: "revoked",
        revoked_at: "2026-06-30T08:00:00Z",
      }),
    ],
    invitations: [],
    staff: [person({ active: false, name: "Stary Podwykonawca" })],
  });
  const current = filterPeople(rows, {
    show: "current",
    account: "",
    role: "",
  });
  const former = filterPeople(rows, { show: "former", account: "", role: "" });
  expect(current.map((row) => row.name)).toEqual(["Jan Wójcik"]);
  expect(former.map((row) => row.name).sort()).toEqual([
    "Stary Podwykonawca",
    "byly@example.com",
  ]);
  expect(
    filterPeople(rows, { show: "all", account: "none", role: "" }).map(
      (row) => row.name,
    ),
  ).toEqual(["Stary Podwykonawca"]);
});

test("management is what a role lets one run, not its name", () => {
  expect(managesTeam({ permissions: ["booking.appointment.manage"] })).toBe(
    true,
  );
  expect(
    managesTeam({ permissions: ["organization.members.manage_limited"] }),
  ).toBe(true);
  expect(
    managesTeam({ permissions: ["booking.appointment.read", "farms.manage"] }),
  ).toBe(false);
});

const day = (over: Partial<PeopleDay["items"][number]> = {}) => ({
  staff_id: "s-1",
  works: [
    { starts_at: "2026-09-24T04:00:00Z", ends_at: "2026-09-24T14:00:00Z" },
  ],
  time_off: [],
  busy: [],
  ...over,
});

test("today: away, on a visit until the end of back-to-back ones, free, free from", () => {
  const at = (iso: string) => new Date(iso);
  expect(todayState(day(), false, at("2026-09-24T08:00:00Z"))).toEqual({
    kind: "noVisits",
  });
  expect(
    todayState(
      day({
        time_off: [
          {
            starts_at: "2026-09-23T22:00:00Z",
            ends_at: "2026-09-26T22:00:00Z",
            reason: null,
          },
        ],
      }),
      true,
      at("2026-09-24T08:00:00Z"),
    ),
  ).toEqual({ kind: "away", until: "2026-09-26T22:00:00Z" });
  const busy = day({
    busy: [
      { starts_at: "2026-09-24T06:00:00Z", ends_at: "2026-09-24T08:00:00Z" },
      { starts_at: "2026-09-24T08:00:00Z", ends_at: "2026-09-24T10:00:00Z" },
    ],
  });
  expect(todayState(busy, true, at("2026-09-24T07:00:00Z"))).toEqual({
    kind: "busy",
    until: "2026-09-24T10:00:00.000Z",
  });
  expect(todayState(busy, true, at("2026-09-24T05:00:00Z"))).toEqual({
    kind: "free",
  });
  expect(todayState(day(), true, at("2026-09-24T02:00:00Z"))).toEqual({
    kind: "freeFrom",
    from: "2026-09-24T04:00:00.000Z",
  });
  expect(todayState(day(), true, at("2026-09-24T15:00:00Z"))).toEqual({
    kind: "off",
  });
});

test("a week reads the way people say it", () => {
  const names = ["Pn", "Wt", "Śr", "Cz", "Pt", "Sb", "Nd"];
  const rule = (weekday: number, start = "06:00:00", end = "16:00:00") => ({
    weekday,
    local_start: start,
    local_end: end,
    location_name: "Baza",
  });
  expect(
    hoursSummary(
      [0, 1, 2, 3, 4].map((day) => rule(day)),
      (day) => names[day],
    ),
  ).toEqual(["Pn–Pt 06:00–16:00 · Baza"]);
  expect(
    hoursSummary(
      [rule(0), rule(2), rule(5, "08:00:00", "12:00:00")],
      (day) => names[day],
    ),
  ).toEqual(["Pn, Śr 06:00–16:00 · Baza", "Sb 08:00–12:00 · Baza"]);
});
