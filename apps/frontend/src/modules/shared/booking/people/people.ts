import type {
  InvitationSummary,
  MembershipSummary,
  PeopleDay,
  Person,
} from "@saas-core/api-client";

/**
 * The company's people as the team screen shows them (ADR-058 §1): an
 * account, an invitation and a calendar entry are three records of one
 * person, joined here. The API keeps them apart because booking is optional:
 * without it the list is just the accounts.
 */

export type AccountState =
  "active" | "suspended" | "invited" | "expired" | "none" | "revoked";

export type PersonRow = {
  /** The row's own key: the calendar entry, else the membership or invitation. */
  key: string;
  /** What `/panel/team/<id>` takes: the calendar entry, else the membership. */
  cardId?: string;
  name: string;
  email?: string;
  /** Null when the viewer may not see it (management and the person only). */
  phone?: string | null;
  member?: MembershipSummary;
  invitation?: InvitationSummary;
  staff?: Person;
  /** The account's role, or the role the invitation will give. */
  role?: string;
  account: AccountState;
  /** Works here now; a former employee is not current (filter "Pokaż"). */
  current: boolean;
  /** Services and hours: the calendar offers them (ADR-058). */
  takesVisits: boolean;
  self: boolean;
  /** Since when (a member) or until when (an invitation). */
  since?: string;
};

const CURRENT = new Set(["active", "suspended"]);

function memberName(member: MembershipSummary): string {
  return [member.first_name, member.last_name].join(" ").trim() || member.email;
}

function accountOf(member: MembershipSummary | undefined): AccountState {
  if (!member) return "none";
  if (member.status === "active" || member.status === "suspended")
    return member.status;
  return "revoked";
}

/**
 * One row per person: entries first, each with the account or invitation it
 * stands for, then the accounts and invitations no entry names. A resent
 * invitation is a new row of the API, so an entry that still names the first
 * one finds the waiting one by its e-mail.
 */
export function joinPeople({
  members,
  invitations,
  staff,
  userId,
}: {
  members: MembershipSummary[];
  invitations: InvitationSummary[];
  staff: Person[];
  userId?: string;
}): PersonRow[] {
  const byId = new Map(members.map((member) => [member.id, member]));
  const usedMembers = new Set<string>();
  const usedInvitations = new Set<string>();
  const open = invitations.filter((item) =>
    ["pending", "expired"].includes(item.status),
  );
  const waitingFor = (email: string) =>
    open
      .filter((item) => item.email === email)
      .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];

  const rows: PersonRow[] = staff.map((entry) => {
    const member = entry.membership_id
      ? byId.get(entry.membership_id)
      : undefined;
    if (member) usedMembers.add(member.id);
    const named = entry.invitation_id
      ? invitations.find((item) => item.id === entry.invitation_id)
      : undefined;
    const invitation =
      member || !named
        ? undefined
        : open.some((item) => item.id === named.id)
          ? named
          : waitingFor(named.email);
    if (invitation) usedInvitations.add(invitation.id);
    const account: AccountState = member
      ? accountOf(member)
      : invitation
        ? invitation.status === "expired"
          ? "expired"
          : "invited"
        : "none";
    return {
      key: entry.id,
      cardId: entry.id,
      name: entry.name,
      email: member?.email ?? invitation?.email,
      phone: entry.phone,
      member,
      invitation,
      staff: entry,
      role: member?.role ?? invitation?.role,
      // An account taken away leaves the person working without one.
      account: account === "revoked" ? "none" : account,
      current: entry.active,
      takesVisits: entry.service_ids.length > 0 && entry.has_hours,
      self: Boolean(userId && member?.user_id === userId),
      since: member?.joined_at ?? invitation?.expires_at ?? entry.created_at,
    };
  });

  for (const member of members) {
    if (usedMembers.has(member.id)) continue;
    rows.push({
      key: member.id,
      cardId: member.id,
      name: memberName(member),
      email: member.email,
      member,
      role: member.role,
      account: accountOf(member),
      current: CURRENT.has(member.status),
      takesVisits: false,
      self: member.user_id === userId,
      since: member.joined_at,
    });
  }

  const emails = new Set(
    members
      .filter((member) => CURRENT.has(member.status))
      .map((member) => member.email),
  );
  for (const invitation of open) {
    if (usedInvitations.has(invitation.id) || emails.has(invitation.email))
      continue;
    // One row per address: the newest invitation stands for the older ones.
    if (waitingFor(invitation.email)?.id !== invitation.id) continue;
    rows.push({
      key: invitation.id,
      name: invitation.email,
      email: invitation.email,
      invitation,
      role: invitation.role,
      account: invitation.status === "expired" ? "expired" : "invited",
      current: true,
      takesVisits: false,
      self: false,
      since: invitation.expires_at,
    });
  }
  return rows;
}

export type ShowFilter = "current" | "former" | "all";
export type AccountFilter = "" | "active" | "invited" | "none" | "suspended";

export function filterPeople(
  rows: PersonRow[],
  {
    show,
    account,
    role,
  }: { show: ShowFilter; account: AccountFilter; role: string },
): PersonRow[] {
  return rows.filter(
    (row) =>
      (show === "all" || (show === "current") === row.current) &&
      (!account ||
        (account === "invited"
          ? row.account === "invited" || row.account === "expired"
          : row.account === account)) &&
      (!role || row.role === role),
  );
}

export type TodayState =
  | { kind: "noVisits" }
  | { kind: "away"; until: string }
  | { kind: "busy"; until: string }
  | { kind: "free" }
  | { kind: "freeFrom"; from: string }
  | { kind: "off" };

type Span = { from: number; to: number };

function spans(items: { starts_at: string; ends_at: string }[]): Span[] {
  return items
    .map((item) => ({
      from: Date.parse(item.starts_at),
      to: Date.parse(item.ends_at),
    }))
    .sort((a, b) => a.from - b.from);
}

/** Back-to-back visits are one stretch of work: "busy until" its end. */
function merged(items: Span[]): Span[] {
  const out: Span[] = [];
  for (const item of items) {
    const last = out.at(-1);
    if (last && item.from <= last.to) last.to = Math.max(last.to, item.to);
    else out.push({ ...item });
  }
  return out;
}

/**
 * The "Dziś" column at `now`: away, on a visit, free, or free from when.
 * Worked out in the browser from one read of the day, so the same answer
 * serves the list, the card and, later, the assignment dialog.
 */
export function todayState(
  day: PeopleDay["items"][number] | undefined,
  takesVisits: boolean,
  now: Date,
): TodayState {
  if (!takesVisits) return { kind: "noVisits" };
  const at = now.getTime();
  const away = day?.time_off.find(
    (item) => Date.parse(item.starts_at) <= at && Date.parse(item.ends_at) > at,
  );
  if (away) return { kind: "away", until: away.ends_at };
  const busy = merged(spans(day?.busy ?? []));
  const current = busy.find((item) => item.from <= at && item.to > at);
  if (current)
    return { kind: "busy", until: new Date(current.to).toISOString() };
  const blocked = merged([
    ...busy,
    ...spans(day?.time_off ?? []).map(({ from, to }) => ({ from, to })),
  ]);
  for (const work of spans(day?.works ?? [])) {
    let start = Math.max(work.from, at);
    for (const block of blocked)
      if (block.from <= start && block.to > start) start = block.to;
    if (start < work.to)
      return start <= at
        ? { kind: "free" }
        : { kind: "freeFrom", from: new Date(start).toISOString() };
  }
  return { kind: "off" };
}

/** "Pn–Pt 06:00–16:00 · Baza": a week told the way people say it. */
export function hoursSummary(
  hours: {
    weekday: number;
    local_start: string;
    local_end: string;
    location_name: string;
  }[],
  dayName: (weekday: number) => string,
): string[] {
  const groups = new Map<string, number[]>();
  for (const rule of hours) {
    const key = `${rule.local_start.slice(0, 5)}–${rule.local_end.slice(0, 5)} · ${rule.location_name}`;
    groups.set(key, [...(groups.get(key) ?? []), rule.weekday]);
  }
  return [...groups].map(([key, days]) => {
    const sorted = [...new Set(days)].sort((a, b) => a - b);
    const runs: string[] = [];
    let first = sorted[0];
    for (let index = 1; index <= sorted.length; index += 1) {
      const day = sorted[index];
      const previous = sorted[index - 1];
      if (day === previous + 1) continue;
      runs.push(
        first === previous
          ? dayName(first)
          : previous === first + 1
            ? `${dayName(first)}, ${dayName(previous)}`
            : `${dayName(first)}–${dayName(previous)}`,
      );
      first = day;
    }
    return `${runs.join(", ")} ${key}`;
  });
}
