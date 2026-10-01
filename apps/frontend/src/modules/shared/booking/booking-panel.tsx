"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { useLocale, useTimeZone, useTranslations } from "next-intl";
import {
  CalendarPlusIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  EyeIcon,
  PlusIcon,
  Settings2Icon,
} from "lucide-react";

import {
  ApiProblemError,
  getBookingCatalog,
  getPeopleDay,
  listBookingAppointments,
  listPeople,
  listTeams,
  type BookingAppointment,
  type BookingCatalog,
  type PeopleDay,
  type Person,
  type StaffTeam,
} from "@saas-core/api-client";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  DataTable,
  DataTableFilter,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import { cn } from "@saas-core/ui/lib/utils";

import { PanelPage, PanelToolbar } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import {
  AppointmentDialog,
  CrewBadges,
  crewNames,
  NewAppointmentDialog,
  StatusBadge,
  STATUSES,
  statusLabel,
  statusStyle,
  VisitPlace,
} from "./appointment-dialogs";
import {
  addDays,
  addMonths,
  dateFormat,
  formatDay,
  formatDayRange,
  formatWhen,
  wallClock,
  weekStart,
} from "./calendar-time";
import { DayBoard } from "./day-board";
import { boardRows } from "./day-board-model";
import { CrewDialog } from "./dispatch/crew-dialog";

type View = "day" | "week" | "month" | "list";
/** The list is the month as a table: the same arrows, sortable and searchable. */
const VIEWS: View[] = ["day", "week", "month", "list"];
const DAY = /^\d{4}-\d{2}-\d{2}$/;
/** The view a person last chose on this device (answer 1C, 29.09). */
const VIEW_KEY = "saas-core.calendar.view";

function storedView(key?: string): View | undefined {
  if (!key) return undefined;
  try {
    const value = localStorage.getItem(`${VIEW_KEY}:${key}`);
    return VIEWS.includes(value as View) ? (value as View) : undefined;
  } catch {
    return undefined;
  }
}
type OpenAppointment = (
  appointment: BookingAppointment,
  opener: HTMLElement,
) => void;

const focusRing =
  "outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

/** On the visit as the server counts it for „Moje wizyty”: lead or crew. */
// A lead taken off a visit that waits for somebody else only leaves their
// name on it (ADR-058 §2).
const onVisit = (item: BookingAppointment, staffId: string) =>
  (item.staff_id === staffId && !item.needs_assignment) ||
  item.crew.some((person) => person.staff_id === staffId);

/** The lead and how many more: a card has room for one name. */
function crewShort(item: BookingAppointment) {
  const [lead, ...rest] = item.crew;
  if (!lead) return "";
  return rest.length ? `${lead.name} +${rest.length}` : lead.name;
}

/**
 * The team's appointments by day, week or month. Services, staff and working
 * hours are set up in Settings; this screen only links there.
 */
export function BookingPanel({
  canManage = true,
  canUseInventory = false,
  timeZone,
  viewKey,
}: {
  /** booking.appointment.manage: plan, move and cancel appointments. */
  canManage?: boolean;
  /** inventory.use: pick the products a visit takes (ADR-055). */
  canUseInventory?: boolean;
  /** The organization's zone: days and times are the business's own. */
  timeZone?: string;
  /** Whose device memory the chosen view lives under; none: no memory. */
  viewKey?: string;
} = {}) {
  const t = useTranslations("Calendar");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const appZone = useTimeZone();
  const zone = timeZone ?? appZone ?? "UTC";
  const today = wallClock(new Date(), zone).day;
  // The view, the day and the filters live in the address (plan: phase 2):
  // a person's card links to their visits, and back or a refresh keeps them.
  const params = useSearchParams();
  const asked = (name: string) => params?.get(name) ?? "";
  const [catalog, setCatalog] = useState<BookingCatalog>();
  const [teams, setTeams] = useState<StaffTeam[]>([]);
  const [appointments, setAppointments] = useState<BookingAppointment[]>();
  const [hasAny, setHasAny] = useState(false);
  const [problem, setProblem] = useState<"load" | "plan" | "access">();
  const [reloads, setReloads] = useState(0);
  const [view, setView] = useState<View>(() =>
    VIEWS.includes(asked("view") as View)
      ? (asked("view") as View)
      : (storedView(viewKey) ?? "week"),
  );
  // A link or a day's heading moves the view; only the switch is a choice.
  const chooseView = (next: View) => {
    setView(next);
    if (!viewKey) return;
    try {
      localStorage.setItem(`${VIEW_KEY}:${viewKey}`, next);
    } catch {
      // Private windows and blocked storage: the view is just not remembered.
    }
  };
  const [board, setBoard] = useState<{ people: Person[]; day: PeopleDay }>();
  const [onlyScheduled, setOnlyScheduled] = useState(false);
  const [plan, setPlan] = useState<{ staffId: string; time: string }>();
  // A vacancy on the board and the block that opened it, for focus to return.
  const [assigning, setAssigning] = useState<{
    appointment: BookingAppointment;
    opener: HTMLElement;
  }>();
  const [cursor, setCursor] = useState(() =>
    DAY.test(asked("date")) ? asked("date") : today,
  );
  const [staffFilter, setStaffFilter] = useState(() => asked("staff"));
  const [serviceFilter, setServiceFilter] = useState(() => asked("service"));
  const [selected, setSelected] = useState<BookingAppointment>();
  const [detailsOpen, setDetailsOpen] = useState(false);
  // "Zaplanuj wizytę" on a person's card opens the form with them chosen.
  const [creating, setCreating] = useState(
    () => canManage && asked("new") === "1",
  );
  const [notice, setNotice] = useState("");
  const opener = useRef<HTMLElement | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const mine = staffFilter === "mine";
  const chosenTeam = staffFilter.startsWith("team:")
    ? teams.find((team) => `team:${team.id}` === staffFilter)
    : undefined;
  const chosenStaff =
    staffFilter && !mine && !staffFilter.startsWith("team:") ? staffFilter : "";

  useEffect(() => {
    const query = new URLSearchParams();
    if (view !== "week") query.set("view", view);
    if (cursor !== today) query.set("date", cursor);
    if (staffFilter) query.set("staff", staffFilter);
    if (serviceFilter) query.set("service", serviceFilter);
    const search = query.toString();
    // Replace, not push: the arrows would otherwise fill the history.
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${search ? `?${search}` : ""}`,
    );
  }, [cursor, serviceFilter, staffFilter, today, view]);
  const refresh = () => setReloads((value) => value + 1);

  const byDay = useMemo(() => {
    const days = new Map<string, BookingAppointment[]>();
    for (const item of appointments ?? []) {
      if (chosenStaff && !onVisit(item, chosenStaff)) continue;
      if (
        chosenTeam &&
        !chosenTeam.member_ids.some((staffId) => onVisit(item, staffId))
      )
        continue;
      if (serviceFilter && item.service_name !== serviceFilter) continue;
      const day = wallClock(item.starts_at, zone).day;
      const list = days.get(day);
      if (list) list.push(item);
      else days.set(day, [item]);
    }
    return days;
  }, [appointments, chosenStaff, chosenTeam, serviceFilter, zone]);

  // An appointment keeps the service name it was booked under, so the filter
  // offers those names too, not only today's catalogue.
  const serviceNames = useMemo(
    () =>
      [
        ...new Set([
          ...(catalog?.services ?? []).map((item) => item.name),
          ...(appointments ?? []).map((item) => item.service_name),
        ]),
      ].sort((a, b) => a.localeCompare(b, locale)),
    [appointments, catalog, locale],
  );

  const days = useMemo(() => {
    if (view === "day") return [cursor];
    if (view === "list") {
      const first = `${cursor.slice(0, 7)}-01`;
      const count =
        (Date.parse(addMonths(cursor, 1)) - Date.parse(first)) / 86_400_000;
      return Array.from({ length: count }, (_, index) => addDays(first, index));
    }
    const first = weekStart(
      view === "week" ? cursor : `${cursor.slice(0, 7)}-01`,
    );
    const last =
      view === "week"
        ? addDays(first, 6)
        : addDays(weekStart(addDays(addMonths(cursor, 1), -1)), 6);
    const count = (Date.parse(last) - Date.parse(first)) / 86_400_000 + 1;
    return Array.from({ length: count }, (_, index) => addDays(first, index));
  }, [cursor, view]);

  // Only what the view shows; whether the calendar is empty at all is a
  // separate question, or an empty week would pass for an empty company.
  const from = days[0];
  const until = addDays(days[days.length - 1], 1);
  useEffect(() => {
    let current = true;
    Promise.all([
      getBookingCatalog(),
      listBookingAppointments({ ...(mine ? { mine } : {}), from, to: until }),
      listBookingAppointments({ limit: 1 }),
      // Teams only help whoever plans; without them the forms still work.
      canManage ? listTeams().catch(() => []) : Promise.resolve([]),
    ])
      .then(([nextCatalog, nextAppointments, first, nextTeams]) => {
        if (!current) return;
        setCatalog(nextCatalog);
        setTeams(nextTeams);
        setAppointments(nextAppointments);
        // The open visit as it is now: a crew saved from elsewhere has a new
        // version, and the details must save with that one.
        setSelected((current) =>
          current
            ? (nextAppointments.find((item) => item.id === current.id) ??
              current)
            : current,
        );
        setHasAny(first.length > 0);
        setProblem(undefined);
      })
      .catch((error: unknown) => {
        if (!current) return;
        const code = error instanceof ApiProblemError ? error.problem.code : "";
        setProblem(
          code === "entitlement_required"
            ? "plan"
            : code === "organization_permission_denied"
              ? "access"
              : "load",
        );
      });
    return () => {
      current = false;
    };
  }, [canManage, from, mine, reloads, until]);

  // The day board's people and their day (plan: phase 4); without them the
  // day stays a list, as it is for one person or for somebody who sees only
  // themselves.
  useEffect(() => {
    if (view !== "day" || mine) return;
    let current = true;
    Promise.all([listPeople(), getPeopleDay(cursor)])
      .then(([people, day]) => {
        if (current) setBoard({ people, day });
      })
      .catch(() => {
        if (current) setBoard(undefined);
      });
    return () => {
      current = false;
    };
  }, [cursor, mine, reloads, view]);

  const title =
    view === "day"
      ? formatDay(cursor, locale, {
          weekday: "long",
          day: "numeric",
          month: "long",
          year: "numeric",
        })
      : view === "week"
        ? formatDayRange(days[0], days[6], locale)
        : // The month and the list show the same month.
          formatDay(cursor, locale, { month: "long", year: "numeric" });

  const move = (step: number) =>
    setCursor(
      view === "day"
        ? addDays(cursor, step)
        : view === "week"
          ? addDays(cursor, 7 * step)
          : addMonths(cursor, step),
    );

  // The opening button can be gone when a dialog closes (the appointment
  // moved to another day); focus then lands on the calendar's heading.
  const restoreFocus = () =>
    opener.current?.isConnected ? opener.current : heading.current;

  const openAppointment: OpenAppointment = (appointment, target) => {
    opener.current = target;
    setSelected(appointment);
    setDetailsOpen(true);
  };

  const openDay = (day: string) => {
    setCursor(day);
    setView("day");
    // The day's button is not part of the day view; keep focus on the page.
    heading.current?.focus();
  };

  const startCreating = (target: HTMLElement) => {
    opener.current = target;
    setCreating(true);
  };

  // A booking needs a service and a place; without them the form cannot work.
  const ready = Boolean(catalog?.services.length && catalog.locations.length);

  const problemNotice = problem ? (
    <div
      className="flex flex-wrap items-center gap-3 rounded-lg border border-destructive/30 p-4"
      role="alert"
    >
      <p className="text-sm text-destructive">
        {t(
          problem === "plan"
            ? "notInPlan"
            : problem === "access"
              ? "noAccess"
              : "loadError",
        )}
      </p>
      {problem === "load" ? (
        <Button onClick={refresh} variant="outline">
          {t("retry")}
        </Button>
      ) : problem === "plan" ? (
        <Link
          className={buttonVariants({ variant: "outline" })}
          href="/panel/settings/billing"
        >
          {t("openBilling")}
        </Link>
      ) : null}
    </div>
  ) : null;

  const emptyState =
    !catalog || !appointments ? null : !ready && canManage ? (
      <EmptyState
        action={
          <Link className={buttonVariants()} href="/panel/settings/services">
            <Settings2Icon aria-hidden="true" />
            {t("settingsLink")}
          </Link>
        }
        text={t("setupText")}
        title={t("setupTitle")}
      />
    ) : !hasAny && !mine ? (
      <EmptyState
        action={
          canManage && ready ? (
            <Button onClick={(event) => startCreating(event.currentTarget)}>
              <PlusIcon aria-hidden="true" />
              {t("firstAppointment")}
            </Button>
          ) : null
        }
        text={canManage && ready ? t("emptyText") : t("emptyReadOnly")}
        title={t("emptyTitle")}
      />
    ) : null;

  const listColumns: ColumnDef<BookingAppointment, unknown>[] = [
    {
      id: "when",
      accessorFn: (item) => new Date(item.starts_at),
      header: t("when"),
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <span
          className={cn(
            "font-medium tabular-nums",
            item.status === "canceled" && "line-through",
          )}
        >
          {formatWhen(item, locale, zone)}
        </span>
      ),
    },
    { id: "customer", accessorKey: "customer_name", header: t("customer") },
    // Only where a module says where its visits are: an empty column is noise.
    ...(appointments?.some((item) => item.place)
      ? [
          {
            id: "town",
            accessorFn: (item: BookingAppointment) => item.place ?? "",
            header: t("town"),
          },
        ]
      : []),
    { id: "service", accessorKey: "service_name", header: t("service") },
    {
      id: "staff",
      accessorFn: (item) => crewNames(item, t),
      header: t("crew"),
      cell: ({ row: { original: item } }) => (
        <span className="flex flex-wrap items-center gap-2">
          {crewNames(item, t) || t("crewNobody")}
          <CrewBadges appointment={item} />
        </span>
      ),
    },
    {
      id: "status",
      accessorFn: (item) => statusLabel(t, item.status),
      header: t("statusColumn"),
      cell: ({ row: { original: item } }) => (
        <StatusBadge status={item.status} />
      ),
    },
    {
      id: "actions",
      header: t("actions"),
      meta: { actions: true },
      cell: ({ row: { original: item } }) => (
        <RowActions
          items={[
            {
              label: t("details"),
              icon: <EyeIcon aria-hidden="true" />,
              inline: true,
              onSelect: (trigger) => {
                if (trigger) openAppointment(item, trigger);
              },
            },
          ]}
          label={t("actionsFor", { customer: item.customer_name })}
        />
      ),
    },
  ];

  // The board: everybody the day holds, then the filters. Fewer than two
  // people is the list — one person needs no board (plan: phase 4).
  const dayItems = (appointments ?? []).filter(
    (item) =>
      wallClock(item.starts_at, zone).day === cursor &&
      (!serviceFilter || item.service_name === serviceFilter),
  );
  const boardData =
    view === "day" && board && board.day.date === cursor && !mine
      ? board
      : undefined;
  const everyone = boardData
    ? boardRows({
        people: boardData.people,
        day: boardData.day,
        appointments: dayItems,
        scheduled: false,
        only: null,
      })
    : [];
  const showBoard = everyone.length >= 2;

  const views = {
    list: () => (
      <DataTable
        caption={t("listCaption", { month: title })}
        columns={listColumns}
        data={days.flatMap((day) => byDay.get(day) ?? [])}
        getRowId={(item) => item.id}
        labels={{ ...labels, empty: t("noAppointmentsMonth") }}
        searchable
        searchText={(item) =>
          [
            item.customer_name,
            item.place ?? "",
            item.service_name,
            ...item.crew.map((person) => person.name),
          ].join(" ")
        }
        toolbar={filters}
      />
    ),
    day: () => {
      if (showBoard && boardData)
        return (
          <DayBoard
            canManage={canManage}
            day={cursor}
            now={new Date()}
            onAssign={(appointment, target) =>
              setAssigning({ appointment, opener: target })
            }
            onOpen={openAppointment}
            onPlan={(staffId, time, target) => {
              opener.current = target;
              setPlan({ staffId, time });
              setCreating(true);
            }}
            peopleDay={boardData.day}
            rows={boardRows({
              people: boardData.people,
              day: boardData.day,
              appointments: dayItems,
              scheduled: onlyScheduled,
              only: chosenStaff
                ? new Set([chosenStaff])
                : chosenTeam
                  ? new Set(chosenTeam.member_ids)
                  : null,
            })}
            services={catalog?.services ?? []}
            teams={teams}
            vacancies={dayItems.filter(
              (item) => item.status === "confirmed" && item.needs_assignment,
            )}
            zone={zone}
          />
        );
      const items = byDay.get(cursor) ?? [];
      return items.length ? (
        <ol className="space-y-2">
          {items.map((item) => (
            <li key={item.id}>
              <AppointmentCard
                appointment={item}
                onOpen={openAppointment}
                wide
                zone={zone}
              />
            </li>
          ))}
        </ol>
      ) : (
        <p className="rounded-xl border p-6 text-sm text-muted-foreground">
          {t("noAppointmentsDay")}
        </p>
      );
    },
    week: () => (
      <ol className="grid gap-3 lg:grid-cols-7">
        {days.map((day) => {
          const items = byDay.get(day) ?? [];
          return (
            <li
              className="min-w-0 space-y-2 rounded-xl border bg-card/50 p-2"
              key={day}
            >
              <h3>
                <DayButton
                  count={items.length}
                  day={day}
                  onOpen={openDay}
                  today={today}
                />
              </h3>
              {items.length ? (
                <ul className="space-y-2">
                  {items.map((item) => (
                    <li key={item.id}>
                      <AppointmentCard
                        appointment={item}
                        onOpen={openAppointment}
                        zone={zone}
                      />
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="px-2 pb-1 text-xs text-muted-foreground">
                  {t("noAppointments")}
                </p>
              )}
            </li>
          );
        })}
      </ol>
    ),
    month: () => (
      <div className="space-y-1">
        <div
          aria-hidden="true"
          className="grid grid-cols-7 text-center text-xs font-medium text-muted-foreground"
        >
          {days.slice(0, 7).map((day) => (
            <span key={day}>
              {formatDay(day, locale, { weekday: "short" })}
            </span>
          ))}
        </div>
        <ol className="grid grid-cols-7 gap-px overflow-hidden rounded-xl border bg-border">
          {days.map((day) => {
            const items = byDay.get(day) ?? [];
            return (
              <li
                className={cn(
                  "flex min-h-20 min-w-0 flex-col gap-1 bg-background p-1 sm:min-h-32",
                  day.slice(0, 7) !== cursor.slice(0, 7) &&
                    "bg-muted/50 text-muted-foreground",
                )}
                key={day}
              >
                <DayButton
                  count={items.length}
                  day={day}
                  month
                  onOpen={openDay}
                  today={today}
                />
                <ul className="hidden space-y-1 sm:block">
                  {items.slice(0, 3).map((item) => (
                    <li key={item.id}>
                      <MonthAppointment
                        appointment={item}
                        onOpen={openAppointment}
                        zone={zone}
                      />
                    </li>
                  ))}
                </ul>
                {items.length > 3 ? (
                  <button
                    className={cn(
                      "hidden min-h-8 rounded-md px-1.5 text-left text-xs font-medium text-primary hover:underline sm:block pointer-coarse:min-h-11",
                      focusRing,
                    )}
                    onClick={() => openDay(day)}
                    type="button"
                  >
                    {t("more", { count: items.length - 3 })}
                    <span className="sr-only">
                      {", "}
                      {formatDay(day, locale, {
                        day: "numeric",
                        month: "long",
                      })}
                    </span>
                  </button>
                ) : null}
              </li>
            );
          })}
        </ol>
      </div>
    ),
  };

  // Who and what: the same two filters above the grids and in the list's row.
  const filters = (
    <>
      <DataTableFilter
        id="calendar-staff"
        label={t("staffFilter")}
        onChange={(event) => setStaffFilter(event.target.value)}
        value={staffFilter}
      >
        <option value="">{t("allStaff")}</option>
        <option value="mine">{t("mine")}</option>
        {teams.length ? (
          <optgroup label={t("teamsGroup")}>
            {teams.map((team) => (
              <option key={team.id} value={`team:${team.id}`}>
                {team.name}
              </option>
            ))}
          </optgroup>
        ) : null}
        {teams.length ? (
          <optgroup label={t("staffGroup")}>
            {catalog?.staff.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </optgroup>
        ) : (
          catalog?.staff.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))
        )}
      </DataTableFilter>
      <DataTableFilter
        id="calendar-service"
        label={t("serviceFilter")}
        onChange={(event) => setServiceFilter(event.target.value)}
        value={serviceFilter}
      >
        <option value="">{t("allServices")}</option>
        {serviceNames.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </DataTableFilter>
      {showBoard ? (
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input
            checked={onlyScheduled}
            className="size-4 accent-primary"
            onChange={(event) => setOnlyScheduled(event.target.checked)}
            type="checkbox"
          />
          {t("onlyScheduled")}
        </label>
      ) : null}
    </>
  );

  return (
    <PanelPage
      actions={
        canManage ? (
          <>
            <Link
              className={buttonVariants({ variant: "ghost" })}
              href="/panel/settings/services"
            >
              <Settings2Icon aria-hidden="true" />
              {t("settingsLink")}
            </Link>
            {ready ? (
              <Button
                onClick={(event) => {
                  setPlan(undefined);
                  startCreating(event.currentTarget);
                }}
              >
                <PlusIcon aria-hidden="true" />
                {t("newAppointment")}
              </Button>
            ) : null}
          </>
        ) : null
      }
      description={t("description", { zone: zone.replaceAll("_", " ") })}
      eyebrow={t("eyebrow")}
      notice={notice}
      title={t("title")}
    >
      <section aria-labelledby="calendar-range" className="space-y-3">
        <PanelToolbar>
          <Button onClick={() => setCursor(today)} variant="outline">
            {t("today")}
          </Button>
          <Button
            aria-label={t(`previous_${view}`)}
            onClick={() => move(-1)}
            size="icon"
            variant="outline"
          >
            <ChevronLeftIcon aria-hidden="true" />
          </Button>
          <Button
            aria-label={t(`next_${view}`)}
            onClick={() => move(1)}
            size="icon"
            variant="outline"
          >
            <ChevronRightIcon aria-hidden="true" />
          </Button>
          <h2
            aria-live="polite"
            className="ml-1 text-lg font-semibold outline-none first-letter:uppercase sm:text-xl"
            id="calendar-range"
            ref={heading}
            tabIndex={-1}
          >
            {title}
          </h2>
          <div
            aria-label={t("view")}
            className="flex rounded-lg border p-0.5 max-sm:w-full sm:ml-auto"
            role="group"
          >
            {VIEWS.map((item) => (
              <Button
                aria-pressed={view === item}
                className="max-sm:flex-1"
                key={item}
                onClick={() => chooseView(item)}
                variant={view === item ? "secondary" : "ghost"}
              >
                {t(`view_${item}`)}
              </Button>
            ))}
          </div>
        </PanelToolbar>

        {/* The list has its own row with search; the grids have these. */}
        {view === "list" ? null : (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            {filters}
            {/* The board has a legend of its own under the rows. */}
            <ul
              aria-label={t("legend")}
              className={cn(
                // A phone's cards spell their status out; the legend only
                // pushes them down there.
                "flex flex-wrap gap-2 max-sm:hidden lg:ml-auto",
                showBoard && view === "day" && "hidden",
              )}
            >
              {STATUSES.map((status) => (
                <li key={status}>
                  <StatusBadge status={status} />
                </li>
              ))}
            </ul>
          </div>
        )}

        {problem && !appointments ? (
          problemNotice
        ) : !appointments ? (
          <div aria-busy="true" className="grid gap-3 lg:grid-cols-7">
            <span className="sr-only">{t("loading")}</span>
            {Array.from({ length: 7 }, (_, index) => (
              <div
                className="h-24 animate-pulse rounded-xl bg-muted lg:h-48"
                key={index}
              />
            ))}
          </div>
        ) : (
          <>
            {problemNotice}
            {emptyState}
            {views[view]()}
          </>
        )}
      </section>

      <AppointmentDialog
        appointment={selected}
        canManage={canManage}
        canUseInventory={canUseInventory}
        catalog={catalog}
        onChanged={(appointment) => {
          setSelected(appointment);
          refresh();
        }}
        onOpenChange={setDetailsOpen}
        open={detailsOpen}
        restoreFocus={restoreFocus}
        teams={teams}
        zone={zone}
      />
      {catalog ? (
        <NewAppointmentDialog
          canUseInventory={canUseInventory}
          catalog={catalog}
          day={cursor}
          // A free window on the board names the person and the time.
          staffId={plan?.staffId ?? chosenStaff}
          time={plan?.time}
          onCreated={(appointment) => {
            setCreating(false);
            setPlan(undefined);
            setNotice(
              t("created", {
                customer: appointment.customer_name,
                when: formatWhen(appointment, locale, zone),
              }),
            );
            setCursor(wallClock(appointment.starts_at, zone).day);
            refresh();
          }}
          onOpenChange={setCreating}
          open={creating}
          restoreFocus={restoreFocus}
          teams={teams}
          zone={zone}
        />
      ) : null}
      {assigning ? (
        <CrewDialog
          appointment={assigning.appointment}
          finalFocus={assigning.opener.isConnected ? assigning.opener : null}
          onConflict={refresh}
          onOpenChange={(value) =>
            value ? undefined : setAssigning(undefined)
          }
          onSaved={() => {
            setNotice(
              t("assigned", { customer: assigning.appointment.customer_name }),
            );
            setAssigning(undefined);
            refresh();
          }}
          teams={teams}
          zone={zone}
        />
      ) : null}
    </PanelPage>
  );
}

function EmptyState({
  action,
  text,
  title,
}: {
  action: ReactNode;
  text: string;
  title: string;
}) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed bg-muted/30 p-6">
      <CalendarPlusIcon aria-hidden="true" className="size-8 text-primary" />
      <h3 className="font-semibold">{title}</h3>
      <p className="max-w-xl text-sm text-muted-foreground">{text}</p>
      {action}
    </div>
  );
}

/** A day's heading in the week and month grids; it opens the day view. */
function DayButton({
  count,
  day,
  month = false,
  onOpen,
  today,
}: {
  count: number;
  day: string;
  month?: boolean;
  onOpen: (day: string) => void;
  today: string;
}) {
  const t = useTranslations("Calendar");
  const locale = useLocale();
  const number = (
    <span
      className={cn(
        "flex size-7 items-center justify-center rounded-full tabular-nums",
        day === today && "bg-primary font-semibold text-primary-foreground",
      )}
    >
      {Number(day.slice(8))}
    </span>
  );
  const appointments = count ? `, ${t("count", { count })}` : "";
  return (
    <button
      aria-current={day === today ? "date" : undefined}
      className={cn(
        "flex min-h-11 w-full items-center gap-2 rounded-lg px-2 text-left text-sm font-medium hover:bg-muted",
        month && "flex-col justify-center gap-0.5 px-0 sm:items-start sm:px-1",
        focusRing,
      )}
      onClick={() => onOpen(day)}
      type="button"
    >
      {month ? (
        <>
          {/* The number is inside the spoken date, so the name keeps it. */}
          <span aria-hidden="true">{number}</span>
          {count ? (
            <span
              aria-hidden="true"
              className="text-[0.7rem] font-semibold text-primary sm:hidden"
            >
              {count}
            </span>
          ) : null}
          <span className="sr-only">
            {formatDay(day, locale, {
              weekday: "long",
              day: "numeric",
              month: "long",
            })}
            {appointments}
          </span>
        </>
      ) : (
        <>
          <span className="text-muted-foreground">
            {formatDay(day, locale, { weekday: "short" })}
          </span>{" "}
          {number}
          <span className="sr-only">{appointments}</span>
        </>
      )}
    </button>
  );
}

function AppointmentCard({
  appointment,
  onOpen,
  wide = false,
  zone,
}: {
  appointment: BookingAppointment;
  onOpen: OpenAppointment;
  /** The day view: one row per appointment on wider screens. */
  wide?: boolean;
  zone: string;
}) {
  const t = useTranslations("Calendar");
  const locale = useLocale();
  // The town says where better than the company's location; the day view
  // names the location only for a visit without one.
  const place = wide && !appointment.place ? appointment.location_name : null;
  // The crew gets a line of its own: a narrow week column still says who.
  const details = [appointment.service_name, place];
  // „+1” is for the eye; a screen reader hears every name.
  const spoken = [appointment.service_name, crewNames(appointment, t), place];
  return (
    <button
      className={cn(
        "flex min-h-11 w-full flex-col items-start gap-1 rounded-lg border border-l-4 bg-background p-2.5 text-left text-sm transition-colors hover:bg-muted",
        wide && "sm:flex-row sm:items-center sm:gap-4",
        statusStyle(appointment.status).border,
        focusRing,
      )}
      onClick={(event) => onOpen(appointment, event.currentTarget)}
      type="button"
    >
      <span
        className={cn(
          "font-semibold tabular-nums",
          wide && "sm:w-36 sm:shrink-0",
          appointment.status === "canceled" && "line-through",
        )}
      >
        {dateFormat(locale, {
          hour: "2-digit",
          minute: "2-digit",
          timeZone: zone,
        }).formatRange(
          new Date(appointment.starts_at),
          new Date(appointment.ends_at),
        )}
      </span>{" "}
      {/* Spaces between the parts keep the spoken name from running together. */}
      <span className={cn("w-full min-w-0", wide && "sm:flex-1")}>
        <span className="block truncate font-medium">
          {appointment.customer_name}
        </span>{" "}
        <VisitPlace className="text-xs font-medium" place={appointment.place} />{" "}
        <span className="block truncate text-xs text-muted-foreground">
          <span aria-hidden="true">{details.filter(Boolean).join(" · ")}</span>
          <span className="sr-only">{spoken.filter(Boolean).join(", ")}</span>
        </span>
        {appointment.crew.length ? (
          <span
            aria-hidden="true"
            className="block truncate text-xs text-muted-foreground"
          >
            {crewShort(appointment)}
          </span>
        ) : null}
      </span>{" "}
      <span className="flex flex-wrap gap-1">
        <StatusBadge status={appointment.status} />{" "}
        <CrewBadges appointment={appointment} short={!wide} />
      </span>
    </button>
  );
}

/** The month grid's short form: start time and customer, the rest spoken. */
function MonthAppointment({
  appointment,
  onOpen,
  zone,
}: {
  appointment: BookingAppointment;
  onOpen: OpenAppointment;
  zone: string;
}) {
  const t = useTranslations("Calendar");
  const locale = useLocale();
  const { icon: Icon, border } = statusStyle(appointment.status);
  return (
    <button
      className={cn(
        "flex min-h-8 w-full flex-col justify-center rounded-md border-l-4 bg-muted/60 px-1.5 py-0.5 text-left text-xs hover:bg-muted pointer-coarse:min-h-11",
        border,
        focusRing,
      )}
      onClick={(event) => onOpen(appointment, event.currentTarget)}
      type="button"
    >
      <span className="flex w-full min-w-0 items-center gap-1">
        <Icon aria-hidden="true" className="size-3.5 shrink-0" />
        <span
          className={cn(
            "tabular-nums",
            appointment.status === "canceled" && "line-through",
          )}
        >
          {dateFormat(locale, {
            hour: "2-digit",
            minute: "2-digit",
            timeZone: zone,
          }).format(new Date(appointment.starts_at))}
        </span>{" "}
        <span className="truncate">{appointment.customer_name}</span>
      </span>{" "}
      <VisitPlace
        className="w-full text-muted-foreground"
        place={appointment.place}
      />
      <span className="sr-only">
        {`, ${[
          statusLabel(t, appointment.status),
          appointment.service_name,
          crewNames(appointment, t),
        ]
          .filter(Boolean)
          .join(", ")}`}
      </span>
    </button>
  );
}
