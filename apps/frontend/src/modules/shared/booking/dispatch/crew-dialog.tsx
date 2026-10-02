"use client";

import { useCallback, useEffect, useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";

import {
  ApiProblemError,
  assignCrew,
  getCrewCandidates,
  type BookingAppointment,
  type CrewCandidate,
  type StaffTeam,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  DataTableFilter,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { useDataTableLabels } from "#lib/data-table-labels";
import { dateFormat, formatWhen, wallClock } from "../calendar-time";
import { problemText } from "../people/person-dialogs";
import { visitName } from "../visit-name";

/**
 * „Zmień osoby” and „Przydziel” (ADR-058 §9, board 9): who could do this
 * visit, and why not when they cannot. Saving names the crew version the
 * office looked at, so two offices never overwrite each other.
 */
export function CrewDialog({
  appointment,
  teams,
  zone,
  onSaved,
  onOpenChange,
  onConflict,
  finalFocus,
}: {
  appointment: BookingAppointment;
  teams: StaffTeam[];
  zone: string;
  onSaved: (saved: BookingAppointment) => void;
  onOpenChange: (open: boolean) => void;
  /** Somebody changed the crew meanwhile: the caller fetches the visit again. */
  onConflict?: () => void;
  finalFocus?: HTMLElement | null;
}) {
  const t = useTranslations("Dispatch");
  const common = useTranslations("Common");
  const locale = useLocale();
  const format = useFormatter();
  const labels = useDataTableLabels();
  const [everyone, setEveryone] = useState(false);
  const [team, setTeam] = useState("");
  const [people, setPeople] = useState<CrewCandidate[]>();
  const [chosen, setChosen] = useState(
    () => new Set(appointment.crew.map((person) => person.staff_id)),
  );
  const [lead, setLead] = useState(
    () => appointment.crew.find((person) => person.lead)?.staff_id ?? "",
  );
  const [notify, setNotify] = useState(true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [key] = useState(() => crypto.randomUUID());

  const load = useCallback(async () => {
    try {
      setPeople(await getCrewCandidates(appointment.id, { everyone }));
    } catch (error) {
      setProblem(problemText(error, t("failed"), t("forbidden")));
    }
  }, [appointment.id, everyone, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load on open
    void load();
  }, [load]);

  const time = (value: string) =>
    dateFormat(locale, {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: zone,
    }).format(new Date(value));
  const day = (value: string) =>
    dateFormat(locale, {
      weekday: "short",
      day: "numeric",
      month: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: zone,
    }).format(new Date(value));
  // An absence ending at midnight is told by its last whole day.
  const lastDay = (value: string) =>
    wallClock(value, zone).time === "00:00"
      ? dateFormat(locale, {
          weekday: "short",
          day: "numeric",
          month: "numeric",
          timeZone: zone,
        }).format(new Date(Date.parse(value) - 1))
      : day(value);
  const teamNames = new Map(teams.map((item) => [item.id, item.name]));
  const selectable = (person: CrewCandidate) =>
    person.state === "free" || person.on_visit;
  const visible = (people ?? []).filter(
    (person) => !team || person.team_ids.includes(team),
  );
  const leadName = people?.find((person) => person.staff_id === lead)?.name;

  function toggle(person: CrewCandidate, on: boolean) {
    const next = new Set(chosen);
    if (on) next.add(person.staff_id);
    else next.delete(person.staff_id);
    setChosen(next);
    if (on && !lead) setLead(person.staff_id);
    if (!on && lead === person.staff_id) setLead([...next][0] ?? "");
  }

  function addTeam(teamId: string) {
    const members = (people ?? []).filter(
      (person) => person.team_ids.includes(teamId) && selectable(person),
    );
    const next = new Set(chosen);
    for (const person of members) next.add(person.staff_id);
    setChosen(next);
    if (!lead && members[0]) setLead(members[0].staff_id);
  }

  async function save() {
    if (chosen.size === 0) {
      setProblem(t("nobody"));
      return;
    }
    setBusy(true);
    setProblem(undefined);
    try {
      const leadId = chosen.has(lead) ? lead : [...chosen][0];
      const saved = await assignCrew(
        appointment.id,
        {
          staff_ids: [leadId, ...[...chosen].filter((id) => id !== leadId)],
          lead_id: leadId,
          expected_version: appointment.crew_version,
          notify,
        },
        key,
      );
      onSaved(saved);
    } catch (error) {
      setProblem(problemText(error, t("failed"), t("forbidden")));
      if (
        error instanceof ApiProblemError &&
        error.problem.code === "crew_changed"
      )
        onConflict?.();
    } finally {
      setBusy(false);
    }
  }

  const stateText = (person: CrewCandidate) => {
    switch (person.state) {
      case "free":
        return t("state_free");
      case "busy":
        return t("state_busy", { until: time(person.until!) });
      case "time_off":
        return t("state_time_off", { until: lastDay(person.until!) });
      default:
        return person.hours.length
          ? t("state_off_schedule", {
              hours: person.hours
                .map(
                  (range) => `${time(range.starts_at)}–${time(range.ends_at)}`,
                )
                .join(", "),
            })
          : t("state_off_day");
    }
  };

  const columns: ColumnDef<CrewCandidate, unknown>[] = [
    {
      id: "pick",
      header: t("colPick"),
      enableSorting: false,
      cell: ({ row: { original: person } }) => (
        <input
          aria-label={t("pick", { name: person.name })}
          checked={chosen.has(person.staff_id)}
          className="size-4"
          disabled={!selectable(person) && !chosen.has(person.staff_id)}
          onChange={(event) => toggle(person, event.target.checked)}
          type="checkbox"
        />
      ),
    },
    {
      id: "lead",
      header: t("colLead"),
      enableSorting: false,
      cell: ({ row: { original: person } }) =>
        chosen.has(person.staff_id) ? (
          <input
            aria-label={t("leadFor", { name: person.name })}
            checked={lead === person.staff_id}
            className="size-4"
            name="crew-lead"
            onChange={() => setLead(person.staff_id)}
            type="radio"
          />
        ) : (
          <span aria-hidden="true">—</span>
        ),
    },
    {
      id: "person",
      accessorKey: "name",
      header: t("colPerson"),
      meta: { primary: true },
      cell: ({ row: { original: person } }) => (
        <>
          <p className="font-medium">{person.name}</p>
          <p className="text-sm text-muted-foreground">
            {[
              person.team_ids
                .map((id) => teamNames.get(id))
                .filter(Boolean)
                .join(", "),
              person.account === "none"
                ? [t("noAccount"), person.phone].filter(Boolean).join(" · ")
                : person.account === "invited"
                  ? t("invited")
                  : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </>
      ),
    },
    {
      id: "now",
      header: t("colNow"),
      enableSorting: false,
      cell: ({ row: { original: person } }) => stateText(person),
    },
    {
      id: "day",
      header: t("colDay"),
      enableSorting: false,
      cell: ({ row: { original: person } }) =>
        t("dayLoad", {
          visits: person.day_visits,
          hours: format.number(person.day_minutes / 60, {
            maximumFractionDigits: 1,
          }),
        }),
    },
    {
      id: "next",
      header: t("colNext"),
      enableSorting: false,
      cell: ({ row: { original: person } }) =>
        person.next_free ? day(person.next_free) : "—",
    },
  ];

  const customerChoice = appointment.requested_team?.name;
  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent
        className="sm:max-w-4xl"
        closeLabel={common("close")}
        finalFocus={() => finalFocus ?? true}
      >
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <DialogHeader>
            <DialogTitle>
              {t(appointment.needs_assignment ? "titleAssign" : "titleChange", {
                customer: visitName(appointment),
              })}
            </DialogTitle>
            <DialogDescription>
              {t("summary", {
                when: formatWhen(appointment, locale, zone),
                service: appointment.service_name,
                place: appointment.location_name,
                count: appointment.staff_required,
              })}
            </DialogDescription>
          </DialogHeader>
          {customerChoice || appointment.customer_notes ? (
            <div className="space-y-1 text-sm">
              {customerChoice ? (
                <p>{t("customerChoice", { team: customerChoice })}</p>
              ) : null}
              {appointment.customer_notes ? (
                <p className="text-muted-foreground">
                  {t("notes", { notes: appointment.customer_notes })}
                </p>
              ) : null}
            </div>
          ) : null}
          <DataTable
            caption={t("caption")}
            columns={columns}
            data={visible}
            getRowId={(person) => person.staff_id}
            labels={{ ...labels, empty: t("noCandidates") }}
            loading={!people}
            toolbar={
              <>
                {teams.length ? (
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="sr-only">{t("addTeam")}</span>
                    <NativeSelect
                      aria-label={t("addTeam")}
                      onChange={(event) => {
                        if (event.target.value) addTeam(event.target.value);
                        event.target.value = "";
                      }}
                      value=""
                    >
                      <option value="">{t("addTeam")}</option>
                      {teams.map((item) => (
                        <option key={item.id} value={item.id}>
                          {t("teamOption", {
                            name: item.name,
                            count: item.member_ids.length,
                          })}
                        </option>
                      ))}
                    </NativeSelect>
                  </label>
                ) : null}
                {teams.length ? (
                  <DataTableFilter
                    id="crew-team"
                    label={t("filterTeam")}
                    onChange={(event) => setTeam(event.target.value)}
                    value={team}
                  >
                    <option value="">{t("filterTeamAll")}</option>
                    {teams.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </DataTableFilter>
                ) : null}
                <DataTableFilter
                  id="crew-show"
                  label={t("filterShow")}
                  onChange={(event) =>
                    setEveryone(event.target.value === "all")
                  }
                  value={everyone ? "all" : "service"}
                >
                  <option value="service">{t("showService")}</option>
                  <option value="all">{t("showAll")}</option>
                </DataTableFilter>
              </>
            }
          />
          <p className="text-sm text-muted-foreground">{t("order")}</p>
          <label className="flex items-center gap-2 text-sm">
            <input
              checked={notify}
              className="size-4"
              onChange={(event) => setNotify(event.target.checked)}
              type="checkbox"
            />
            {t("notify")}
          </label>
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DialogFooter className="items-center">
            <p className="mr-auto text-sm" role="status">
              {t("chosen", {
                count: chosen.size,
                need: appointment.staff_required,
              })}
              {leadName && chosen.has(lead)
                ? t("leadIs", { name: leadName })
                : null}
            </p>
            <DialogClose render={<Button variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button disabled={busy} type="submit">
              {t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
