"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  ChevronRightIcon,
  IdCardIcon,
  PencilIcon,
  PhoneIcon,
  UserPlusIcon,
} from "lucide-react";

import {
  ApiProblemError,
  createInvitation,
  endPerson,
  getBookingCatalog,
  getPeopleDay,
  getSeatUsage,
  invitePerson,
  listInvitations,
  listMemberships,
  listPeople,
  listRoles,
  restorePerson,
  revokeInvitation,
  transferOwnership,
  updateMembership,
  type BookingCatalog,
  type InvitationSummary,
  type MembershipSummary,
  type OrganizationSummary,
  type PeopleDay,
  type Person,
  type RoleCatalog,
  type SeatUsage,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  DataTableFilter,
  RowActions,
  type ColumnDef,
  type RowAction,
} from "@saas-core/ui/components/data-table";

import { PanelPage } from "#components/panel/panel-page";
import { Link, useRouter } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import { allows, type PanelAccess } from "#lib/panel-navigation";
import { ChangeRoleDialog } from "../../../core/organizations/role-dialog";
import { managesTeam } from "../../../core/organizations/role-groups";
import { useRoleLabel } from "../../../core/organizations/role-labels";
import { wallClock } from "../calendar-time";
import { AddPersonDialog } from "./add-person-dialog";
import {
  ConfirmDialog,
  EditPersonDialog,
  InviteDialog,
  LinkAccountDialog,
  problemText,
  TimeOffDialog,
} from "./person-dialogs";
import {
  filterPeople,
  joinPeople,
  todayState,
  type AccountFilter,
  type PersonRow,
  type ShowFilter,
  type TodayState,
} from "./people";

const MEMBERS_READ = "organization.members.read";
const collator = new Intl.Collator("pl", { sensitivity: "base" });
const MEMBERS_MANAGE = "organization.members.manage";
const MEMBERS_MANAGE_LIMITED = "organization.members.manage_limited";
const OWNERSHIP_TRANSFER = "organization.ownership.transfer";
const BOOKING_MANAGE = "booking.appointment.manage";
const SCHEDULE_OWN = "booking.schedule.own";

type Booking = {
  catalog: BookingCatalog;
  people: Person[];
  day: PeopleDay;
};
type Loaded = {
  members: MembershipSummary[];
  invitations: InvitationSummary[];
  roles: RoleCatalog;
  seats: SeatUsage | null;
  /** Null where the company's plan or type has no calendar. */
  booking: Booking | null;
};
type Dialog = {
  kind:
    | "role"
    | "edit"
    | "timeOff"
    | "invite"
    | "link"
    | "suspend"
    | "resume"
    | "end"
    | "transfer";
  row: PersonRow;
};

/** A calendar the plan or the type does not have is not an error here. */
function withoutCalendar(error: unknown): boolean {
  return (
    error instanceof ApiProblemError &&
    (error.problem.status === 403 || error.problem.status === 404)
  );
}

/** "until 14:00" today, "until 26.09" for the last whole day away. */
export function useUntil(zone: string) {
  const format = useFormatter();
  return (instant: string, now: Date) => {
    const end = wallClock(instant, zone);
    if (end.time === "00:00") {
      const last = wallClock(new Date(Date.parse(instant) - 1), zone).day;
      return format.dateTime(new Date(`${last}T12:00:00Z`), {
        day: "2-digit",
        month: "2-digit",
        timeZone: "UTC",
      });
    }
    return end.day === wallClock(now, zone).day
      ? end.time
      : `${format.dateTime(new Date(`${end.day}T12:00:00Z`), {
          day: "2-digit",
          month: "2-digit",
          timeZone: "UTC",
        })} ${end.time}`;
  };
}

/** The "Dziś" words for a state; the list and the card say it the same way. */
export function useTodayText(zone: string) {
  const t = useTranslations("People");
  const until = useUntil(zone);
  return (state: TodayState, now: Date) => {
    switch (state.kind) {
      case "away":
        return t("today_away", { until: until(state.until, now) });
      case "busy":
        return t("today_busy", { until: until(state.until, now) });
      case "freeFrom":
        return t("today_freeFrom", { from: wallClock(state.from, zone).time });
      default:
        return t(`today_${state.kind}`);
    }
  };
}

/**
 * Zespół › Pracownicy (plan, board 1): everyone who works for the company, with
 * an account in the panel or without one, current and former. The calendar
 * adds what a person does and where they are today; without it, this is the
 * list of accounts.
 */
export function PeoplePanel({
  organization,
  userId,
  access,
}: {
  organization: OrganizationSummary | null;
  userId?: string;
  access: PanelAccess;
}) {
  const t = useTranslations("People");
  const team = useTranslations("TeamPage");
  const labels = useDataTableLabels();
  const format = useFormatter();
  const router = useRouter();
  const permissions = new Set(organization?.permissions);
  const canRead = permissions.has(MEMBERS_READ);
  const canManageMembers = permissions.has(MEMBERS_MANAGE);
  const canInvite = canManageMembers || permissions.has(MEMBERS_MANAGE_LIMITED);
  const canTransfer =
    organization?.role === "owner" && permissions.has(OWNERSHIP_TRANSFER);
  const calendarModule = allows(access, { module: "shared.booking" });
  const canOwnSchedule = permissions.has(SCHEDULE_OWN);
  const zone = organization?.timezone ?? "UTC";

  const [data, setData] = useState<Loaded>();
  // An installed module is not a bought one: where the plan has no calendar
  // the list is the accounts, and nothing on it edits a calendar entry.
  const canBook =
    calendarModule && permissions.has(BOOKING_MANAGE) && Boolean(data?.booking);
  const [failed, setFailed] = useState(false);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<string>();
  const [show, setShow] = useState<ShowFilter>("current");
  const [account, setAccount] = useState<AccountFilter>("");
  const [role, setRole] = useState("");
  const [adding, setAdding] = useState(false);
  const [dialog, setDialog] = useState<Dialog>();
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);
  const [now] = useState(() => new Date());
  const roleLabel = useRoleLabel(data?.roles, organization?.organization_type);
  const todayText = useTodayText(zone);

  const load = useCallback(async () => {
    try {
      const [members, invitations, roles, seats, booking] = await Promise.all([
        // Former staff is personnel history: management's (ADR-058 §9).
        listMemberships({ includeFormer: canInvite }),
        listInvitations(),
        listRoles(),
        getSeatUsage().catch(() => null),
        calendarModule
          ? Promise.all([getBookingCatalog(), listPeople(), getPeopleDay()])
              .then(([catalog, people, day]) => ({ catalog, people, day }))
              .catch((error: unknown) => {
                if (withoutCalendar(error)) return null;
                throw error;
              })
          : Promise.resolve(null),
      ]);
      // Strongest first — the order a ladder of roles is read in.
      roles.roles.sort((a, b) => b.permissions.length - a.permissions.length);
      setData({ members, invitations, roles, seats, booking });
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [calendarModule, canInvite]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    if (canRead) void load();
  }, [canRead, load]);

  const rows = useMemo(
    () =>
      data
        ? joinPeople({
            members: data.members,
            invitations: data.invitations,
            staff: data.booking?.people ?? [],
            userId,
          })
        : [],
    [data, userId],
  );

  const limited = new Set(
    data?.roles.roles.filter((item) => item.limited).map((item) => item.key),
  );
  // Never the owner; with limited management only the type's limited roles.
  const manages = (key?: string) =>
    Boolean(key) &&
    canInvite &&
    key !== "owner" &&
    (canManageMembers || limited.has(key!));
  const managing = (key?: string) => {
    const found = data?.roles.roles.find((item) => item.key === key);
    return found ? managesTeam(found) : false;
  };
  // The office first, then the people who work with an account, without one,
  // and those still invited — the order of the plan's board 1.
  const rank = (row: PersonRow) =>
    row.self
      ? -1
      : !row.current
        ? 4
        : row.member
          ? managing(row.role)
            ? 0
            : 1
          : row.account === "none"
            ? 2
            : 3;
  const visible = filterPeople(rows, { show, account, role }).sort(
    (a, b) => rank(a) - rank(b) || collator.compare(a.name, b.name),
  );
  const days = new Map(
    (data?.booking?.day.items ?? []).map((item) => [item.staff_id, item]),
  );
  const unlinked = (data?.members ?? []).filter(
    (member) =>
      member.status === "active" &&
      !data?.booking?.people.some(
        (person) => person.membership_id === member.id,
      ),
  );
  const date = (value: string) =>
    format.dateTime(new Date(value), { dateStyle: "medium" });

  async function run(action: () => Promise<unknown>, done: string) {
    setProblem(undefined);
    setNotice("");
    try {
      await action();
      setNotice(done);
      await load();
    } catch (error) {
      setProblem(problemText(error, t("failed"), t("forbidden")));
    }
  }

  function ask(
    kind: Dialog["kind"],
    row: PersonRow,
    trigger: HTMLElement | null,
  ) {
    setReturnTo(trigger);
    setProblem(undefined);
    setDialog({ kind, row });
  }

  function actions(row: PersonRow): RowAction[] {
    const items: RowAction[] = [];
    const { member, staff, invitation } = row;
    if (row.cardId)
      items.push({
        label: t("openCard", { name: row.name }),
        icon: <IdCardIcon aria-hidden="true" />,
        inline: true,
        link: <Link href={`/panel/team/${row.cardId}`} />,
      });
    if (row.phone)
      items.push({
        label: t("call", { name: row.name }),
        icon: <PhoneIcon aria-hidden="true" />,
        inline: true,
        link: <a href={`tel:${row.phone.replaceAll(" ", "")}`} />,
      });
    // Editing is always in sight where it is allowed (ADR-057).
    const editable =
      canBook && row.current && (staff || member?.status === "active");
    if (editable || (row.self && staff))
      items.push({
        label: t("editFor", { name: row.name }),
        icon: <PencilIcon aria-hidden="true" />,
        inline: true,
        onSelect: (trigger) => ask("edit", row, trigger),
      });
    if (!row.current) {
      if (staff && canBook)
        items.push({
          label: t("restore"),
          onSelect: () =>
            void run(
              () => restorePerson(staff.id),
              t("restored", { name: row.name }),
            ),
        });
      return items;
    }
    if (canBook && staff && row.takesVisits)
      items.push({
        label: t("plan"),
        link: <Link href={`/panel/calendar?new=1&staff=${staff.id}`} />,
      });
    if (staff && (canBook || (row.self && canOwnSchedule)))
      items.push({
        label: t("timeOff"),
        onSelect: (trigger) => ask("timeOff", row, trigger),
      });
    if (member?.status === "active" && !row.self && manages(member.role))
      items.push({
        label: t("changeRole"),
        onSelect: (trigger) => ask("role", row, trigger),
      });
    const accountItems: RowAction[] = [];
    if (invitation && canInvite && manages(invitation.role)) {
      if (invitation.status === "expired")
        accountItems.push({
          label: t("resend"),
          onSelect: () =>
            void run(
              () =>
                staff && canBook
                  ? invitePerson(staff.id, {
                      email: invitation.email,
                      role: invitation.role,
                    })
                  : createInvitation({
                      email: invitation.email,
                      role: invitation.role,
                    }),
              t("invited", { email: invitation.email }),
            ),
        });
      accountItems.push({
        label: t("revoke"),
        onSelect: () =>
          void run(
            () => revokeInvitation(invitation.id),
            t("revoked", { email: invitation.email }),
          ),
      });
    } else if (staff && !member && canInvite && canBook) {
      accountItems.push({
        label: t("invite"),
        onSelect: (trigger) => ask("invite", row, trigger),
      });
      if (unlinked.length)
        accountItems.push({
          label: t("link"),
          onSelect: (trigger) => ask("link", row, trigger),
        });
    }
    if (member && !row.self && manages(member.role))
      accountItems.push({
        label: t(member.status === "suspended" ? "resume" : "suspend"),
        onSelect: (trigger) =>
          ask(
            member.status === "suspended" ? "resume" : "suspend",
            row,
            trigger,
          ),
      });
    const endable =
      !row.self &&
      (staff
        ? canBook && (!member || manages(member.role))
        : Boolean(member && manages(member.role)));
    if (endable)
      accountItems.push({
        label: t("end"),
        destructive: true,
        onSelect: (trigger) => ask("end", row, trigger),
      });
    if (
      canTransfer &&
      member?.status === "active" &&
      !row.self &&
      member.role !== "owner"
    )
      accountItems.push({
        label: team("transfer"),
        destructive: true,
        onSelect: (trigger) => ask("transfer", row, trigger),
      });
    accountItems.forEach((item, index) =>
      items.push(
        index === 0 && items.length ? { ...item, separated: true } : item,
      ),
    );
    return items;
  }

  const accountText = (row: PersonRow) => {
    if (!row.current)
      return row.member?.revoked_at
        ? t("formerSince", { date: date(row.member.revoked_at) })
        : t("former");
    if (row.account === "invited")
      return t("state_invited", { date: date(row.invitation!.expires_at) });
    return t(`state_${row.account}`);
  };

  const columns: ColumnDef<PersonRow, unknown>[] = [
    {
      id: "person",
      accessorKey: "name",
      header: t("colPerson"),
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <>
          <p className="font-medium wrap-anywhere">
            {row.cardId ? (
              <Link
                className="rounded-sm hover:underline focus-visible:outline-2 focus-visible:outline-ring"
                href={`/panel/team/${row.cardId}`}
              >
                {row.name}
              </Link>
            ) : (
              row.name
            )}
            {row.self ? (
              <span className="font-normal text-muted-foreground">
                {" "}
                ({t("you")})
              </span>
            ) : null}
          </p>
          {row.phone ? (
            <p className="text-muted-foreground tabular-nums">{row.phone}</p>
          ) : row.email && row.email !== row.name ? (
            <p className="text-muted-foreground wrap-anywhere">{row.email}</p>
          ) : null}
        </>
      ),
    },
    {
      id: "role",
      accessorFn: (row) => (row.role ? roleLabel(row.role) : ""),
      header: t("colRole"),
      cell: ({ row: { original: row } }) => (
        <>
          <p className="flex flex-wrap items-center gap-2 max-md:justify-end">
            {row.role ? roleLabel(row.role) : "—"}
            {row.role && managing(row.role) ? (
              <Badge variant="secondary">{t("manages")}</Badge>
            ) : null}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {accountText(row)}
          </p>
        </>
      ),
    },
    ...(data?.booking
      ? [
          {
            id: "today",
            header: t("colToday"),
            enableSorting: false,
            cell: ({ row: { original: row } }) =>
              row.current
                ? todayText(
                    todayState(
                      row.staff ? days.get(row.staff.id) : undefined,
                      row.takesVisits,
                      now,
                    ),
                    now,
                  )
                : "—",
          } satisfies ColumnDef<PersonRow, unknown>,
        ]
      : []),
    {
      id: "actions",
      header: t("colActions"),
      meta: { actions: true },
      cell: ({ row: { original: row } }) => (
        <RowActions
          items={actions(row)}
          label={t("actionsFor", { name: row.name })}
        />
      ),
    },
  ];

  const current = dialog?.row;
  const close = () => setDialog(undefined);
  const openChange = (open: boolean) => (open ? undefined : close());
  const roleOptions = data?.roles.roles ?? [];

  return (
    <PanelPage
      actions={
        // Without an account to send, adding needs the calendar to hold the person.
        canRead && data && (canInvite || canBook) ? (
          <Button onClick={() => setAdding(true)}>
            <UserPlusIcon aria-hidden="true" />
            {t("add")}
          </Button>
        ) : null
      }
      description={t("description")}
      eyebrow={t("eyebrow")}
      notice={notice}
      title={t("title")}
    >
      {!organization || !canRead ? (
        <p className="text-muted-foreground">
          {organization ? team("noAccess") : team("noOrganization")}
        </p>
      ) : failed ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{team("loadError")}</p>
          <Button onClick={() => void load()} variant="outline">
            {team("retry")}
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          {problem && !dialog ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DataTable
            caption={t("tableCaption")}
            columns={columns}
            data={visible}
            emptyAction={
              <Button
                onClick={() => {
                  setShow("current");
                  setAccount("");
                  setRole("");
                }}
                variant="outline"
              >
                {t("clearFilters")}
              </Button>
            }
            getRowId={(row) => row.key}
            labels={{ ...labels, empty: t("noResults") }}
            loading={!data}
            searchText={(row) =>
              [row.name, row.email, row.phone, row.role && roleLabel(row.role)]
                .filter(Boolean)
                .join(" ")
            }
            searchable
            toolbar={
              <>
                {canInvite ? (
                  <DataTableFilter
                    id="people-show"
                    label={t("show")}
                    onChange={(event) =>
                      setShow(event.target.value as ShowFilter)
                    }
                    value={show}
                  >
                    <option value="current">{t("showCurrent")}</option>
                    <option value="former">{t("showFormer")}</option>
                    <option value="all">{t("showAll")}</option>
                  </DataTableFilter>
                ) : null}
                <DataTableFilter
                  id="people-account"
                  label={t("account")}
                  onChange={(event) =>
                    setAccount(event.target.value as AccountFilter)
                  }
                  value={account}
                >
                  <option value="">{t("accountAll")}</option>
                  <option value="active">{t("state_active")}</option>
                  <option value="invited">{t("accountInvited")}</option>
                  {data?.booking ? (
                    <option value="none">{t("state_none")}</option>
                  ) : null}
                  <option value="suspended">{t("state_suspended")}</option>
                </DataTableFilter>
                <DataTableFilter
                  id="people-role"
                  label={t("role")}
                  onChange={(event) => setRole(event.target.value)}
                  value={role}
                >
                  <option value="">{t("roleAll")}</option>
                  {roleOptions.map((item) => (
                    <option key={item.key} value={item.key}>
                      {roleLabel(item.key)}
                    </option>
                  ))}
                </DataTableFilter>
              </>
            }
          />
          {data &&
          rows.filter((row) => row.current).length <= 1 &&
          canInvite ? (
            <p className="text-muted-foreground">{t("alone")}</p>
          ) : null}
          {data?.seats?.limit != null ? (
            <p className="text-sm text-muted-foreground">
              {t("seats", { used: data.seats.used, limit: data.seats.limit })}
            </p>
          ) : null}
          {data?.booking ? (
            <details className="text-sm">
              <summary className="flex w-max cursor-pointer list-none items-center gap-1.5 font-medium [&::-webkit-details-marker]:hidden">
                <ChevronRightIcon
                  aria-hidden="true"
                  className="size-4 text-muted-foreground"
                />
                {t("accountVsPerson")}
              </summary>
              <p className="max-w-3xl pt-2 pl-6 text-muted-foreground">
                {t("accountVsPersonText")}
              </p>
            </details>
          ) : null}
        </div>
      )}

      {data ? (
        <AddPersonDialog
          booking={
            data.booking
              ? { catalog: data.booking.catalog, people: data.booking.people }
              : null
          }
          canBook={canBook}
          canInvite={canInvite}
          canManageMembers={canManageMembers}
          onAdded={({ name, email }) => {
            setNotice(email ? t("invited", { email }) : t("added", { name }));
            void load();
          }}
          onOpenChange={setAdding}
          open={adding}
          organizationType={organization?.organization_type}
          roles={data.roles}
          seats={data.seats}
        />
      ) : null}

      {data && current?.member ? (
        <ChangeRoleDialog
          canCreateRole={canManageMembers}
          canManage={canManageMembers}
          catalog={data.roles}
          finalFocus={returnTo}
          key={current.key}
          member={dialog?.kind === "role" ? current.member : undefined}
          name={current.name}
          onChanged={() => {
            close();
            setNotice(t("roleChanged", { name: current.name }));
            void load();
          }}
          onOpenChange={openChange}
          organizationType={organization?.organization_type}
        />
      ) : null}

      {data && current && dialog?.kind === "edit" ? (
        <EditPersonDialog
          canManage={canBook}
          catalog={data.booking?.catalog}
          finalFocus={returnTo}
          onOpenChange={openChange}
          onSaved={(name) => {
            close();
            setNotice(t("saved", { name }));
            void load();
          }}
          open
          person={{
            staffId: current.staff?.id,
            membershipId: current.staff ? undefined : current.member?.id,
            name: current.name,
            phone: current.phone ?? "",
            serviceIds: current.staff?.service_ids ?? [],
          }}
        />
      ) : null}

      {current?.staff && dialog?.kind === "timeOff" ? (
        <TimeOffDialog
          finalFocus={returnTo}
          name={current.name}
          onAdded={(result) => {
            close();
            setNotice(
              result.conflicts
                ? t("timeOffConflicts", {
                    name: current.name,
                    count: result.conflicts,
                  })
                : t("timeOffAdded", { name: current.name }),
            );
            void load();
          }}
          onOpenChange={openChange}
          open
          staffId={current.staff.id}
          today={wallClock(now, zone).day}
          zone={zone}
        />
      ) : null}

      {data && current?.staff && dialog?.kind === "invite" ? (
        <InviteDialog
          canManage={canManageMembers}
          catalog={data.roles}
          finalFocus={returnTo}
          name={current.name}
          onInvited={(email) => {
            close();
            setNotice(t("invited", { email }));
            void load();
          }}
          onOpenChange={openChange}
          open
          organizationType={organization?.organization_type}
          staffId={current.staff.id}
        />
      ) : null}

      {current?.staff && dialog?.kind === "link" ? (
        <LinkAccountDialog
          finalFocus={returnTo}
          members={unlinked}
          name={current.name}
          onLinked={() => {
            close();
            setNotice(t("linked", { name: current.name }));
            void load();
          }}
          onOpenChange={openChange}
          open
          staffId={current.staff.id}
        />
      ) : null}

      {current &&
      dialog &&
      ["suspend", "resume", "end", "transfer"].includes(dialog.kind) ? (
        <ConfirmDialog
          confirm={
            dialog.kind === "transfer"
              ? team("transferConfirm")
              : t(`${dialog.kind}Confirm`)
          }
          description={
            dialog.kind === "transfer"
              ? team("transferDescription", {
                  name: current.name,
                  organization: organization?.name ?? "",
                  owner: roleLabel("owner"),
                  admin: roleLabel("admin"),
                })
              : t(`${dialog.kind}Description`, { name: current.name })
          }
          destructive={dialog.kind !== "resume"}
          extra={
            dialog.kind === "end" && current.staff ? (
              <p className="text-sm text-muted-foreground">
                {t("endVisits")}{" "}
                <Link
                  className="font-medium text-primary hover:underline"
                  href={`/panel/calendar?view=list&staff=${current.staff.id}`}
                >
                  {t("endVisitsLink")}
                </Link>
              </p>
            ) : dialog.kind === "transfer" ? (
              <p className="text-sm font-medium">{team("transferSignOut")}</p>
            ) : null
          }
          finalFocus={returnTo}
          onConfirm={async () => {
            try {
              if (dialog.kind === "transfer" && current.member) {
                await transferOwnership(current.member.id);
                // Both sessions end with the transfer (the API revokes them).
                router.replace("/login");
                return undefined;
              }
              if (dialog.kind === "end" && current.staff)
                await endPerson(current.staff.id);
              else if (current.member)
                await updateMembership(current.member.id, {
                  status:
                    dialog.kind === "resume"
                      ? "active"
                      : dialog.kind === "suspend"
                        ? "suspended"
                        : "revoked",
                });
              close();
              setNotice(t(`${dialog.kind}Done`, { name: current.name }));
              await load();
              return undefined;
            } catch (error) {
              return problemText(error, t("failed"), t("forbidden"));
            }
          }}
          onOpenChange={openChange}
          open
          title={
            dialog.kind === "transfer"
              ? team("transferTitle")
              : t(`${dialog.kind}Title`, { name: current.name })
          }
        />
      ) : null}
    </PanelPage>
  );
}
