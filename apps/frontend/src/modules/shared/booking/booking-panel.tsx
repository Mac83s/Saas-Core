"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
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
  listBookingAppointments,
  type BookingAppointment,
  type BookingCatalog,
} from "@saas-core/api-client";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  DataTable,
  DataTableFilter,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import { cn } from "@saas-core/ui/lib/utils";

import { PanelPage } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import {
  AppointmentDialog,
  NewAppointmentDialog,
  StatusBadge,
  STATUSES,
  statusLabel,
  statusStyle,
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

type View = "day" | "week" | "month" | "list";
/** The list is the month as a table: the same arrows, sortable and searchable. */
const VIEWS: View[] = ["day", "week", "month", "list"];
type OpenAppointment = (
  appointment: BookingAppointment,
  opener: HTMLElement,
) => void;

const focusRing =
  "outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

/**
 * The team's appointments by day, week or month. Services, staff and working
 * hours are set up in Settings; this screen only links there.
 */
export function BookingPanel({
  canManage = true,
  canUseInventory = false,
  timeZone,
}: {
  /** booking.appointment.manage: plan, move and cancel appointments. */
  canManage?: boolean;
  /** inventory.use: pick the products a visit takes (ADR-055). */
  canUseInventory?: boolean;
  /** The organization's zone: days and times are the business's own. */
  timeZone?: string;
} = {}) {
  const t = useTranslations("Calendar");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const appZone = useTimeZone();
  const zone = timeZone ?? appZone ?? "UTC";
  const today = wallClock(new Date(), zone).day;
  const [catalog, setCatalog] = useState<BookingCatalog>();
  const [appointments, setAppointments] = useState<BookingAppointment[]>();
  const [problem, setProblem] = useState<"load" | "plan" | "access">();
  const [reloads, setReloads] = useState(0);
  const [view, setView] = useState<View>("week");
  const [cursor, setCursor] = useState(today);
  const [staffFilter, setStaffFilter] = useState("");
  const [serviceFilter, setServiceFilter] = useState("");
  const [selected, setSelected] = useState<BookingAppointment>();
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState("");
  const opener = useRef<HTMLElement | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const mine = staffFilter === "mine";

  useEffect(() => {
    let current = true;
    Promise.all([
      getBookingCatalog(),
      // ponytail: this takes the first 500 appointments by start time, so
      // past 500 in history the newest drop out. The API takes from/to now;
      // asking for the visible range waits on the empty state below, which
      // must know that the calendar is empty, not only this week.
      listBookingAppointments(mine ? { mine } : {}),
    ])
      .then(([nextCatalog, nextAppointments]) => {
        if (!current) return;
        setCatalog(nextCatalog);
        setAppointments(nextAppointments);
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
  }, [mine, reloads]);
  const refresh = () => setReloads((value) => value + 1);

  const byDay = useMemo(() => {
    const days = new Map<string, BookingAppointment[]>();
    for (const item of appointments ?? []) {
      if (staffFilter && !mine && item.staff_id !== staffFilter) continue;
      if (serviceFilter && item.service_name !== serviceFilter) continue;
      const day = wallClock(item.starts_at, zone).day;
      const list = days.get(day);
      if (list) list.push(item);
      else days.set(day, [item]);
    }
    return days;
  }, [appointments, mine, serviceFilter, staffFilter, zone]);

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
    ) : appointments.length === 0 && !mine ? (
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
    { id: "service", accessorKey: "service_name", header: t("service") },
    { id: "staff", accessorKey: "staff_name", header: t("staff") },
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
          [item.customer_name, item.service_name, item.staff_name].join(" ")
        }
        toolbar={filters}
      />
    ),
    day: () => {
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
        {catalog?.staff.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
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
              <Button onClick={(event) => startCreating(event.currentTarget)}>
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
      <section aria-labelledby="calendar-range" className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
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
            className="ml-1 text-xl font-semibold outline-none first-letter:uppercase"
            id="calendar-range"
            ref={heading}
            tabIndex={-1}
          >
            {title}
          </h2>
          <div
            aria-label={t("view")}
            className="flex rounded-lg border p-0.5 sm:ml-auto"
            role="group"
          >
            {VIEWS.map((item) => (
              <Button
                aria-pressed={view === item}
                key={item}
                onClick={() => setView(item)}
                variant={view === item ? "secondary" : "ghost"}
              >
                {t(`view_${item}`)}
              </Button>
            ))}
          </div>
        </div>

        {/* The list has its own row with search; the grids have these. */}
        {view === "list" ? null : (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            {filters}
            <ul
              aria-label={t("legend")}
              className="flex flex-wrap gap-2 lg:ml-auto"
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
        zone={zone}
      />
      {catalog ? (
        <NewAppointmentDialog
          canUseInventory={canUseInventory}
          catalog={catalog}
          day={cursor}
          onCreated={(appointment) => {
            setCreating(false);
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
  const locale = useLocale();
  const details = [
    appointment.service_name,
    appointment.staff_name,
    wide ? appointment.location_name : null,
  ].filter(Boolean);
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
        <span className="block truncate text-xs text-muted-foreground">
          {details.join(" · ")}
        </span>
      </span>{" "}
      <StatusBadge status={appointment.status} />
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
        "flex min-h-8 w-full items-center gap-1 rounded-md border-l-4 bg-muted/60 px-1.5 text-left text-xs hover:bg-muted pointer-coarse:min-h-11",
        border,
        focusRing,
      )}
      onClick={(event) => onOpen(appointment, event.currentTarget)}
      type="button"
    >
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
      <span className="sr-only">
        {`, ${statusLabel(t, appointment.status)}, ${appointment.service_name}, ${appointment.staff_name}`}
      </span>
    </button>
  );
}
