"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { CalendarOffIcon, CalendarPlusIcon, PencilIcon } from "lucide-react";

import {
  ApiProblemError,
  getBookingCatalog,
  getPeopleDay,
  getPerson,
  listBookingAppointments,
  listInvitations,
  listMemberships,
  listPeople,
  listRoles,
  type BookingAppointment,
  type BookingCatalog,
  type InvitationSummary,
  type MembershipSummary,
  type OrganizationSummary,
  type PeopleDay,
  type Person,
  type PersonDetail,
  type RoleCatalog,
  type UserSummary,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import { DataTable, type ColumnDef } from "@saas-core/ui/components/data-table";
import { cn } from "@saas-core/ui/lib/utils";

import { PanelPage, PanelSection } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import { allows, type PanelAccess } from "#lib/panel-navigation";
import { ChangeRoleDialog } from "../../../core/organizations/role-dialog";
import { managesTeam } from "../../../core/organizations/role-groups";
import { useRoleLabel } from "../../../core/organizations/role-labels";
import { StatusBadge } from "../appointment-dialogs";
import { addDays, formatWhen, wallClock } from "../calendar-time";
import { useTodayText } from "./people-panel";
import { EditPersonDialog, TimeOffDialog } from "./person-dialogs";
import { PersonSchedule } from "./person-schedule";
import { hoursSummary, todayState } from "./people";

const MEMBERS_READ = "organization.members.read";
const MEMBERS_MANAGE = "organization.members.manage";
const MEMBERS_MANAGE_LIMITED = "organization.members.manage_limited";
const BOOKING_MANAGE = "booking.appointment.manage";
const SCHEDULE_OWN = "booking.schedule.own";

export type PersonTab = "overview" | "schedule";

type Loaded = {
  detail: PersonDetail | null;
  member?: MembershipSummary;
  invitation?: InvitationSummary;
  roles?: RoleCatalog;
  catalog?: BookingCatalog;
  day?: PeopleDay;
  people: Person[];
  upcoming: BookingAppointment[];
  members: MembershipSummary[];
  /** The calendar answered: an installed module is not a bought one. */
  booking: boolean;
};

function memberName(member: MembershipSummary): string {
  return [member.first_name, member.last_name].join(" ").trim() || member.email;
}

/** Only a missing calendar or a person out of reach; anything else is a failure. */
function absent(error: unknown): boolean {
  return (
    error instanceof ApiProblemError &&
    [403, 404].includes(error.problem.status ?? 0)
  );
}

/**
 * The person's card (plan, boards 4 and 16): who they are, how to reach them,
 * their role and account, where they are today, what they do and when, and
 * their next visits. Its pages are addresses (ADR-057): Przegląd and Grafik;
 * history and results come with phase 5. `personId` is the calendar entry,
 * an account's membership when it has no entry, or "me" — "Moja karta" works
 * for anyone, also without the team screen (owner's answer 3).
 */
export function PersonCard({
  personId,
  tab,
  organization,
  user,
  access,
}: {
  personId: string;
  tab: PersonTab;
  organization: OrganizationSummary | null;
  user: UserSummary | null;
  access: PanelAccess;
}) {
  const t = useTranslations("PersonCard");
  const people = useTranslations("People");
  const locale = useLocale();
  const format = useFormatter();
  const labels = useDataTableLabels();
  const me = personId === "me";
  const userId = user?.id;
  const permissions = new Set(organization?.permissions);
  const canRead = permissions.has(MEMBERS_READ);
  const canManageMembers = permissions.has(MEMBERS_MANAGE);
  const canInvite = canManageMembers || permissions.has(MEMBERS_MANAGE_LIMITED);
  const calendarModule = allows(access, { module: "shared.booking" });
  const canBook = calendarModule && permissions.has(BOOKING_MANAGE);
  const zone = organization?.timezone ?? "UTC";
  const [now] = useState(() => new Date());
  const today = wallClock(now, zone).day;

  const [data, setData] = useState<Loaded | null>();
  const [failed, setFailed] = useState(false);
  const [notice, setNotice] = useState("");
  const [dialog, setDialog] = useState<"edit" | "timeOff" | "role">();
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);
  const roleLabel = useRoleLabel(data?.roles, organization?.organization_type);
  const todayText = useTodayText(zone);

  const load = useCallback(async () => {
    try {
      const optional = <T,>(promise: Promise<T>) =>
        promise.catch((error: unknown) => {
          if (absent(error)) return undefined;
          throw error;
        });
      const [members, invitations, roles] = await Promise.all([
        canRead
          ? listMemberships({ includeFormer: canInvite })
          : Promise.resolve([]),
        canRead ? listInvitations() : Promise.resolve([]),
        optional(listRoles()),
      ]);
      let detail: PersonDetail | null = null;
      let mine: Person[] | undefined;
      if (calendarModule) {
        mine = me ? await optional(listPeople({ mine: true })) : undefined;
        const entry = me ? mine?.[0]?.id : personId;
        detail = entry ? ((await optional(getPerson(entry))) ?? null) : null;
      }
      const member = detail?.membership_id
        ? members.find((item) => item.id === detail?.membership_id)
        : members.find((item) =>
            me ? item.user_id === userId : item.id === personId,
          );
      if (!detail && !member && !me) {
        setData(null);
        return;
      }
      const invitation =
        !member && detail?.invitation_id
          ? invitations.find((item) => item.id === detail?.invitation_id)
          : undefined;
      const [catalog, day, others, upcoming] = detail
        ? await Promise.all([
            optional(getBookingCatalog()),
            optional(getPeopleDay()),
            canRead ? optional(listPeople()) : Promise.resolve(undefined),
            optional(
              listBookingAppointments({
                staffId: detail.id,
                from: today,
                to: addDays(today, 14),
              }),
            ),
          ])
        : [
            // "Edytuj" gives an account its entry, services and all.
            canBook ? await optional(getBookingCatalog()) : undefined,
            undefined,
            undefined,
            undefined,
          ];
      setData({
        detail,
        member,
        invitation,
        roles,
        catalog,
        day,
        people: others ?? [],
        upcoming: (upcoming ?? []).filter((item) => item.status !== "canceled"),
        members,
        booking: Boolean(detail || mine || catalog),
      });
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [
    calendarModule,
    canBook,
    canInvite,
    canRead,
    me,
    personId,
    today,
    userId,
  ]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    void load();
  }, [load]);

  const detail = data?.detail ?? null;
  const member = data?.member;
  const self = me || Boolean(member && member.user_id === user?.id);
  const name =
    detail?.name ??
    (member ? memberName(member) : null) ??
    ([user?.first_name, user?.last_name].join(" ").trim() || user?.email) ??
    "";
  const roleKey = member?.role ?? (self ? organization?.role : undefined);
  const role = data?.roles?.roles.find((item) => item.key === roleKey);
  const since = member?.joined_at ?? detail?.created_at;
  const takesVisits = Boolean(
    detail && detail.service_ids.length && detail.has_hours,
  );
  const canSchedule =
    Boolean(detail?.active) &&
    (canBook || (self && permissions.has(SCHEDULE_OWN)));
  const canEdit =
    (canBook && Boolean(data?.booking)) || (self && Boolean(detail));
  const limited = new Set(
    data?.roles?.roles.filter((item) => item.limited).map((item) => item.key),
  );
  const canChangeRole =
    member?.status === "active" &&
    !self &&
    canInvite &&
    member.role !== "owner" &&
    (canManageMembers || limited.has(member.role));
  const base = `/panel/team/${me ? "me" : personId}`;
  const services = (detail?.service_ids ?? [])
    .map((id) => data?.catalog?.services.find((item) => item.id === id)?.name)
    .filter(Boolean)
    .join(", ");
  const dayName = (weekday: number) => people(`day_${weekday}`);

  const account = () => {
    if (member) {
      if (member.status === "active" || member.status === "suspended")
        return people(`state_${member.status}`);
      return member.revoked_at
        ? people("formerSince", {
            date: format.dateTime(new Date(member.revoked_at), {
              dateStyle: "medium",
            }),
          })
        : people("former");
    }
    if (data?.invitation)
      return data.invitation.status === "expired"
        ? people("state_expired")
        : people("state_invited", {
            date: format.dateTime(new Date(data.invitation.expires_at), {
              dateStyle: "medium",
            }),
          });
    return self ? people("state_active") : people("state_none");
  };

  const facts: [string, ReactNode][] = [
    ...(detail?.phone
      ? ([
          [
            t("phone"),
            <a
              className="hover:underline"
              href={`tel:${detail.phone.replaceAll(" ", "")}`}
              key="phone"
            >
              {detail.phone}
            </a>,
          ],
        ] satisfies [string, ReactNode][])
      : []),
    [
      t("email"),
      member?.email ??
        data?.invitation?.email ??
        (self ? user?.email : null) ??
        "—",
    ],
    [
      t("role"),
      roleKey ? (
        <span className="flex flex-wrap items-center gap-2" key="role">
          {roleLabel(roleKey)}
          {role && managesTeam(role) ? (
            <Badge variant="secondary">{people("manages")}</Badge>
          ) : null}
          {canChangeRole ? (
            <button
              className="font-medium text-primary hover:underline"
              onClick={(event) => {
                setReturnTo(event.currentTarget);
                setDialog("role");
              }}
              type="button"
            >
              {t("changeRole")}
            </button>
          ) : null}
        </span>
      ) : (
        "—"
      ),
    ],
    [t("account"), account()],
    ...(detail
      ? ([
          [
            t("today"),
            detail.active
              ? todayText(
                  todayState(
                    data?.day?.items.find(
                      (item) => item.staff_id === detail.id,
                    ),
                    takesVisits,
                    now,
                  ),
                  now,
                )
              : people("former"),
          ],
          [t("services"), services || "—"],
          [
            t("hours"),
            detail.hours.length
              ? hoursSummary(detail.hours, dayName).join("; ")
              : t("noHours"),
          ],
        ] satisfies [string, ReactNode][])
      : []),
  ];

  const visitColumns: ColumnDef<BookingAppointment, unknown>[] = [
    {
      id: "when",
      accessorFn: (item) => new Date(item.starts_at),
      header: t("colWhen"),
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <span className="font-medium tabular-nums">
          {formatWhen(item, locale, zone)}
        </span>
      ),
    },
    { id: "customer", accessorKey: "customer_name", header: t("colCustomer") },
    { id: "service", accessorKey: "service_name", header: t("colService") },
    {
      id: "status",
      header: t("colStatus"),
      enableSorting: false,
      cell: ({ row: { original: item } }) => (
        <StatusBadge status={item.status} />
      ),
    },
  ];

  const frame = {
    eyebrow: me ? t("myCard") : t("back"),
    eyebrowHref: me ? undefined : "/panel/team",
    notice,
  };

  if (data === undefined && !failed)
    return (
      <PanelPage {...frame} title={t("loading")}>
        <div
          aria-busy="true"
          className="h-40 animate-pulse rounded-xl bg-muted"
        />
      </PanelPage>
    );
  if (failed)
    return (
      <PanelPage {...frame} title={t("title")}>
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{t("loadError")}</p>
          <Button onClick={() => void load()} variant="outline">
            {people("retry")}
          </Button>
        </div>
      </PanelPage>
    );
  if (!data)
    return (
      <PanelPage {...frame} title={t("title")}>
        <p className="text-muted-foreground">{t("notFound")}</p>
      </PanelPage>
    );

  const description = [
    roleKey ? roleLabel(roleKey) : null,
    since
      ? t("since", {
          date: format.dateTime(new Date(since), { dateStyle: "long" }),
        })
      : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <PanelPage
      {...frame}
      actions={
        <>
          {canSchedule && detail ? (
            <Button
              onClick={(event) => {
                setReturnTo(event.currentTarget);
                setDialog("timeOff");
              }}
              variant="outline"
            >
              <CalendarOffIcon aria-hidden="true" />
              {t("timeOff")}
            </Button>
          ) : null}
          {canEdit && (detail?.active ?? member?.status === "active") ? (
            <Button
              onClick={(event) => {
                setReturnTo(event.currentTarget);
                setDialog("edit");
              }}
              variant="outline"
            >
              <PencilIcon aria-hidden="true" />
              {t("edit")}
            </Button>
          ) : null}
          {canBook && takesVisits && detail?.active ? (
            <Link
              className={buttonVariants()}
              href={`/panel/calendar?new=1&staff=${detail.id}`}
            >
              <CalendarPlusIcon aria-hidden="true" />
              {t("plan")}
            </Link>
          ) : null}
        </>
      }
      description={description}
      title={name}
    >
      <section aria-labelledby="person-facts-title">
        <h2 className="sr-only" id="person-facts-title">
          {me ? t("myData") : t("data")}
        </h2>
        <dl className="grid gap-x-8 gap-y-3 rounded-xl border p-4 sm:grid-cols-2">
          {facts.map(([label, value]) => (
            <div className="min-w-0" key={label}>
              <dt className="text-sm text-muted-foreground">{label}</dt>
              <dd className="wrap-anywhere">{value}</dd>
            </div>
          ))}
        </dl>
      </section>

      {detail ? (
        <nav aria-label={t("tabs")}>
          <ul className="flex gap-1 border-b">
            {(
              [
                ["overview", base, t("tabOverview")],
                ["schedule", `${base}/schedule`, t("tabSchedule")],
              ] as const
            ).map(([key, href, label]) => (
              <li key={key}>
                <Link
                  aria-current={tab === key ? "page" : undefined}
                  className={cn(
                    "-mb-px flex min-h-11 items-center border-b-2 border-transparent px-3 text-sm font-medium text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
                    tab === key && "border-primary text-foreground",
                  )}
                  href={href}
                >
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      ) : me && data.booking && !canEdit ? (
        // Management adds itself with "Edytuj"; without the calendar in the
        // plan there is no schedule to be missing from.
        <p className="text-muted-foreground">{t("noEntry")}</p>
      ) : null}

      {detail && tab === "overview" ? (
        <PanelSection
          actions={
            <Link
              className="text-sm font-medium text-primary hover:underline"
              href={`/panel/calendar?view=list&staff=${detail.id}`}
            >
              {t("allInCalendar")}
            </Link>
          }
          title={t("upcoming")}
        >
          <DataTable
            caption={t("upcomingCaption", { name })}
            columns={visitColumns}
            data={data.upcoming}
            getRowId={(item) => item.id}
            labels={{ ...labels, empty: t("noUpcoming") }}
          />
        </PanelSection>
      ) : null}

      {detail && tab === "schedule" ? (
        <PersonSchedule
          canEdit={canSchedule}
          catalog={data.catalog}
          detail={detail}
          onChanged={(next) => setData({ ...data, detail: next })}
          onNotice={setNotice}
          people={data.people}
          today={today}
          zone={zone}
        />
      ) : null}

      {dialog === "edit" ? (
        <EditPersonDialog
          canManage={canBook}
          catalog={data.catalog}
          finalFocus={returnTo}
          onOpenChange={(open) => (open ? undefined : setDialog(undefined))}
          onSaved={(saved) => {
            setDialog(undefined);
            setNotice(people("saved", { name: saved }));
            void load();
          }}
          open
          person={{
            staffId: detail?.id,
            membershipId: detail ? undefined : member?.id,
            name,
            phone: detail?.phone ?? "",
            serviceIds: detail?.service_ids ?? [],
          }}
        />
      ) : null}
      {dialog === "timeOff" && detail ? (
        <TimeOffDialog
          finalFocus={returnTo}
          name={name}
          onAdded={(result) => {
            setDialog(undefined);
            setNotice(
              result.conflicts
                ? people("timeOffConflicts", { name, count: result.conflicts })
                : people("timeOffAdded", { name }),
            );
            void load();
          }}
          onOpenChange={(open) => (open ? undefined : setDialog(undefined))}
          open
          staffId={detail.id}
          today={today}
          zone={zone}
        />
      ) : null}
      {data.roles && member ? (
        <ChangeRoleDialog
          canCreateRole={canManageMembers}
          canManage={canManageMembers}
          catalog={data.roles}
          finalFocus={returnTo}
          key={member.id}
          member={dialog === "role" ? member : undefined}
          name={name}
          onChanged={() => {
            setDialog(undefined);
            setNotice(people("roleChanged", { name }));
            void load();
          }}
          onOpenChange={(open) => (open ? undefined : setDialog(undefined))}
          organizationType={organization?.organization_type}
        />
      ) : null}
    </PanelPage>
  );
}
