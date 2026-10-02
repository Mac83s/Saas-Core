"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckIcon, UsersIcon } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import {
  assignCrew,
  getBookingQueue,
  listTeams,
  type OrganizationSummary,
  type QueueItem,
  type StaffTeam,
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
import { addDays, formatWhen, wallClock, weekStart } from "../calendar-time";
import { problemText } from "../people/person-dialogs";
import { CrewDialog } from "./crew-dialog";
import { visitName, visitPerson } from "../visit-name";

const BOOKING_MANAGE = "booking.appointment.manage";

type When = "" | "today" | "tomorrow" | "week";
type Kind = "" | "auto" | "vacancy";

/**
 * Kalendarz › Do przydzielenia (ADR-058 §3, board 8): visits the office should
 * look at — the people the system chose for a booking from the website, and
 * vacancies after an absence or somebody leaving. Looking at a pick and
 * keeping it („Zostaw”) takes the visit off the list.
 */
export function QueuePanel({
  organization,
}: {
  organization: OrganizationSummary | null;
}) {
  const t = useTranslations("Dispatch");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const router = useRouter();
  const zone = organization?.timezone ?? "UTC";
  const canManage = Boolean(organization?.permissions.includes(BOOKING_MANAGE));
  const [now] = useState(() => new Date());
  const today = wallClock(now, zone).day;
  const [items, setItems] = useState<QueueItem[]>();
  const [teams, setTeams] = useState<StaffTeam[]>([]);
  const [failed, setFailed] = useState(false);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<string>();
  const [when, setWhen] = useState<When>("");
  const [kind, setKind] = useState<Kind>("");
  const [service, setService] = useState("");
  const [open, setOpen] = useState<QueueItem>();
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);

  const load = useCallback(async () => {
    try {
      const [queue, allTeams] = await Promise.all([
        getBookingQueue(),
        listTeams().catch(() => []),
      ]);
      setItems(queue);
      setTeams(allTeams);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    if (canManage) void load();
  }, [canManage, load]);

  const dayOf = useCallback(
    (item: QueueItem) => wallClock(new Date(item.starts_at), zone).day,
    [zone],
  );
  const services = useMemo(
    () => [...new Set((items ?? []).map((item) => item.service_name))].sort(),
    [items],
  );
  // The open visit as the list last brought it: a reload after a conflict
  // hands the dialog the crew version it has to save with.
  const current = open && (items?.find((item) => item.id === open.id) ?? open);
  const visible = (items ?? []).filter((item) => {
    const day = dayOf(item);
    if (when === "today" && day !== today) return false;
    if (when === "tomorrow" && day !== addDays(today, 1)) return false;
    if (
      when === "week" &&
      (day < weekStart(today) || day >= addDays(weekStart(today), 7))
    )
      return false;
    if (kind === "auto" && (!item.auto_assigned || item.needs_assignment))
      return false;
    if (kind === "vacancy" && !item.needs_assignment) return false;
    return !service || item.service_name === service;
  });

  function waited(since: string | null) {
    if (!since) return "";
    const minutes = Math.max(
      1,
      Math.round((now.getTime() - new Date(since).getTime()) / 60000),
    );
    if (minutes < 60) return t("waitMinutes", { count: minutes });
    const hours = Math.round(minutes / 60);
    return hours < 48
      ? t("waitHours", { count: hours })
      : t("waitDays", { count: Math.round(hours / 24) });
  }

  async function keep(item: QueueItem) {
    setProblem(undefined);
    try {
      const lead = item.crew.find((person) => person.lead)?.staff_id;
      await assignCrew(
        item.id,
        {
          staff_ids: item.crew.map((person) => person.staff_id),
          lead_id: lead ?? null,
          expected_version: item.crew_version,
          notify: false,
        },
        crypto.randomUUID(),
      );
      setNotice(t("kept", { customer: visitName(item) }));
      await load();
      router.refresh();
    } catch (error) {
      setProblem(problemText(error, t("failed"), t("forbidden")));
    }
  }

  function actions(item: QueueItem): RowAction[] {
    const day = dayOf(item);
    const list: RowAction[] = [];
    if (!item.needs_assignment)
      list.push({
        label: t("keepFor", { customer: visitName(item) }),
        icon: <CheckIcon aria-hidden="true" />,
        inline: true,
        onSelect: () => void keep(item),
      });
    list.push({
      label: t(item.needs_assignment ? "assignFor" : "changeFor", {
        customer: visitName(item),
      }),
      icon: <UsersIcon aria-hidden="true" />,
      inline: true,
      onSelect: (trigger) => {
        setReturnTo(trigger);
        setOpen(item);
      },
    });
    list.push({
      label: t("openInCalendar"),
      link: <Link href={`/panel/calendar?view=day&date=${day}`} />,
    });
    return list;
  }

  const columns: ColumnDef<QueueItem, unknown>[] = [
    {
      id: "when",
      accessorFn: (item) => new Date(item.starts_at),
      header: t("colWhen"),
      meta: { primary: true },
      cell: ({ row: { original: item } }) => {
        const day = dayOf(item);
        return (
          <>
            <p className="font-medium tabular-nums">
              {formatWhen(item, locale, zone)}
            </p>
            {day === today || day === addDays(today, 1) ? (
              <p className="text-sm text-muted-foreground">
                {day === today ? t("today") : t("tomorrow")}
              </p>
            ) : null}
          </>
        );
      },
    },
    {
      id: "customer",
      accessorFn: visitName,
      header: t("colCustomer"),
      cell: ({ row: { original: item } }) => (
        <>
          <p className="font-medium">{visitName(item)}</p>
          {visitPerson(item) ? (
            <p className="text-sm">{visitPerson(item)}</p>
          ) : null}
          <p className="text-sm text-muted-foreground">
            {[item.customer_phone, item.customer_email]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {item.customer_notes ? (
            <p className="text-sm">„{item.customer_notes}”</p>
          ) : null}
        </>
      ),
    },
    {
      id: "service",
      accessorKey: "service_name",
      header: t("colService"),
      cell: ({ row: { original: item } }) => (
        <>
          <p>{item.service_name}</p>
          {item.staff_required > 1 ? (
            <p className="text-sm text-muted-foreground">
              {t("people", { count: item.staff_required })}
            </p>
          ) : null}
        </>
      ),
    },
    {
      id: "crew",
      header: t("colCrew"),
      enableSorting: false,
      cell: ({ row: { original: item } }) => (
        <div className="space-y-1">
          <p>{item.crew.map((person) => person.name).join(", ") || "—"}</p>
          {item.requested_team ? (
            <p className="text-sm text-muted-foreground">
              {t("customerChoice", { team: item.requested_team.name })}
            </p>
          ) : null}
          {item.needs_assignment ? (
            <Badge variant="destructive">
              {t("vacancy", {
                count: Math.max(item.staff_required - item.crew.length, 1),
              })}
            </Badge>
          ) : (
            <Badge variant="secondary">{t("auto")}</Badge>
          )}
        </div>
      ),
    },
    {
      id: "waiting",
      accessorFn: (item) => item.queued_at ?? "",
      header: t("colWaiting"),
      cell: ({ row: { original: item } }) => (
        <>
          <p>{waited(item.queued_at)}</p>
          {item.queue_reason ? (
            <p className="text-sm text-muted-foreground">
              {t(`reason_${item.queue_reason}` as "reason_public")}
            </p>
          ) : null}
        </>
      ),
    },
    {
      id: "actions",
      header: t("colActions"),
      enableSorting: false,
      meta: { actions: true },
      cell: ({ row: { original: item } }) => (
        <RowActions
          items={actions(item)}
          label={t("moreFor", { customer: visitName(item) })}
        />
      ),
    },
  ];

  return (
    <PanelPage
      description={t("description")}
      eyebrow={t("eyebrow")}
      notice={notice}
      title={t("title")}
    >
      {!canManage ? (
        <p className="text-muted-foreground">{t("noAccess")}</p>
      ) : failed ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{t("loadError")}</p>
          <Button onClick={() => void load()} variant="outline">
            {t("retry")}
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="max-w-3xl text-sm text-muted-foreground">
            {t("legend")}
          </p>
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DataTable
            caption={t("tableCaption")}
            columns={columns}
            data={visible}
            getRowId={(item) => item.id}
            labels={{ ...labels, empty: t("empty") }}
            loading={!items}
            searchText={(item) =>
              [
                item.title,
                item.customer_name,
                item.customer_phone,
                item.customer_email,
                item.service_name,
              ].join(" ")
            }
            searchable
            toolbar={
              <>
                <DataTableFilter
                  id="queue-when"
                  label={t("when")}
                  onChange={(event) => setWhen(event.target.value as When)}
                  value={when}
                >
                  <option value="">{t("whenAll")}</option>
                  <option value="today">{t("whenToday")}</option>
                  <option value="tomorrow">{t("whenTomorrow")}</option>
                  <option value="week">{t("whenWeek")}</option>
                </DataTableFilter>
                <DataTableFilter
                  id="queue-kind"
                  label={t("kind")}
                  onChange={(event) => setKind(event.target.value as Kind)}
                  value={kind}
                >
                  <option value="">{t("kindAll")}</option>
                  <option value="auto">{t("auto")}</option>
                  <option value="vacancy">{t("kindVacancy")}</option>
                </DataTableFilter>
                <DataTableFilter
                  id="queue-service"
                  label={t("service")}
                  onChange={(event) => setService(event.target.value)}
                  value={service}
                >
                  <option value="">{t("serviceAll")}</option>
                  {services.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </DataTableFilter>
              </>
            }
          />
          <p className="text-sm text-muted-foreground">{t("footer")}</p>
        </div>
      )}
      {current ? (
        <CrewDialog
          appointment={current}
          finalFocus={returnTo}
          onConflict={() => void load()}
          onOpenChange={(value) => (value ? undefined : setOpen(undefined))}
          onSaved={() => {
            setNotice(t("assigned", { customer: visitName(current) }));
            setOpen(undefined);
            void load();
            router.refresh();
          }}
          teams={teams}
          zone={zone}
        />
      ) : null}
    </PanelPage>
  );
}
