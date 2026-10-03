"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronRightIcon, PencilIcon, UsersIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  createTeam,
  deleteTeam,
  getPeopleDay,
  listBookingAppointments,
  listPeople,
  listTeams,
  updateTeam,
  type BookingAppointment,
  type OrganizationSummary,
  type PeopleDay,
  type Person,
  type StaffTeam,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
  type ColumnDef,
  type RowAction,
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
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

import { PanelPage } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";
import { addDays, wallClock, weekStart } from "../calendar-time";
import { ConfirmDialog, problemText } from "../people/person-dialogs";
import { todayState } from "../people/people";

const BOOKING_MANAGE = "booking.appointment.manage";
const collator = new Intl.Collator("pl", { sensitivity: "base" });

type Loaded = {
  teams: StaffTeam[];
  people: Person[];
  day: PeopleDay | null;
  week: BookingAppointment[];
};

type Row = {
  team: StaffTeam;
  members: Person[];
  free: number;
  away: Person[];
  visits: number;
};

/**
 * Zespół › Zespoły (ADR-058 §2, board 6): standing groups of people, e.g. a
 * crew that works together. Choosing a team for a visit takes as many of
 * its free members as the service needs; a change here never moves a visit.
 */
export function TeamsPanel({
  organization,
}: {
  organization: OrganizationSummary | null;
}) {
  const t = useTranslations("Teams");
  const labels = useDataTableLabels();
  const canManage = Boolean(organization?.permissions.includes(BOOKING_MANAGE));
  const zone = organization?.timezone ?? "UTC";
  const [now] = useState(() => new Date());
  const today = wallClock(now, zone).day;
  const [data, setData] = useState<Loaded>();
  const [failed, setFailed] = useState(false);
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState<StaffTeam | "new">();
  const [removing, setRemoving] = useState<StaffTeam>();
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);

  const load = useCallback(async () => {
    try {
      const monday = weekStart(today);
      const [teams, people, day, week] = await Promise.all([
        listTeams(),
        listPeople(),
        getPeopleDay().catch(() => null),
        listBookingAppointments({ from: monday, to: addDays(monday, 7) }),
      ]);
      setData({ teams, people, day, week });
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [today]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    if (organization) void load();
  }, [load, organization]);

  const rows = useMemo<Row[]>(() => {
    if (!data) return [];
    const byId = new Map(data.people.map((person) => [person.id, person]));
    const days = new Map(
      (data.day?.items ?? []).map((item) => [item.staff_id, item]),
    );
    return data.teams.map((team) => {
      const members = team.member_ids
        .map((id) => byId.get(id))
        .filter((person): person is Person => Boolean(person))
        .sort((a, b) => collator.compare(a.name, b.name));
      const states = members.map((person) =>
        todayState(
          days.get(person.id),
          person.service_ids.length > 0 && person.has_hours,
          now,
        ),
      );
      const ids = new Set(team.member_ids);
      return {
        team,
        members,
        free: states.filter((state) => state.kind === "free").length,
        away: members.filter((_, index) => states[index].kind === "away"),
        visits: data.week.filter(
          (visit) =>
            visit.status !== "canceled" &&
            visit.crew.some((person) => ids.has(person.staff_id)),
        ).length,
      };
    });
  }, [data, now]);

  const columns: ColumnDef<Row, unknown>[] = [
    {
      id: "team",
      accessorFn: (row) => row.team.name,
      header: t("colTeam"),
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <>
          <p className="font-medium wrap-anywhere">{row.team.name}</p>
          <p className="text-sm text-muted-foreground">
            {t("people", { count: row.members.length })}
          </p>
        </>
      ),
    },
    {
      id: "members",
      header: t("colMembers"),
      enableSorting: false,
      cell: ({ row: { original: row } }) =>
        row.members.map((person) => person.name).join(", ") || "—",
    },
    {
      id: "today",
      header: t("colToday"),
      enableSorting: false,
      cell: ({ row: { original: row } }) =>
        [
          t("freeNow", { free: row.free, total: row.members.length }),
          row.away.length
            ? t("away", { names: row.away.map((p) => p.name).join(", ") })
            : null,
        ]
          .filter(Boolean)
          .join(" · "),
    },
    {
      id: "week",
      accessorFn: (row) => row.visits,
      header: t("colWeek"),
      cell: ({ row: { original: row } }) => (
        <span className="tabular-nums">{row.visits}</span>
      ),
    },
    {
      id: "actions",
      header: t("colActions"),
      enableSorting: false,
      meta: { actions: true },
      cell: ({ row: { original: row } }) =>
        canManage ? (
          <RowActions
            items={teamActions(row.team)}
            label={t("actionsFor", { name: row.team.name })}
          />
        ) : null,
    },
  ];

  function teamActions(team: StaffTeam): RowAction[] {
    return [
      {
        label: t("editFor", { name: team.name }),
        icon: <PencilIcon aria-hidden="true" />,
        inline: true,
        main: true,
        onSelect: (trigger) => {
          setReturnTo(trigger);
          setEditing(team);
        },
      },
      {
        label: t("delete"),
        destructive: true,
        onSelect: (trigger) => {
          setReturnTo(trigger);
          setRemoving(team);
        },
      },
    ];
  }

  return (
    <PanelPage
      actions={
        canManage && data ? (
          <Button
            onClick={(event) => {
              setReturnTo(event.currentTarget);
              setEditing("new");
            }}
          >
            <UsersIcon aria-hidden="true" />
            {t("add")}
          </Button>
        ) : null
      }
      description={t("description")}
      eyebrow={t("eyebrow")}
      notice={notice}
      title={t("title")}
    >
      {!organization ? (
        <p className="text-muted-foreground">{t("noOrganization")}</p>
      ) : failed ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{t("loadError")}</p>
          <Button onClick={() => void load()} variant="outline">
            {t("retry")}
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          <DataTable
            caption={t("tableCaption")}
            columns={columns}
            data={rows}
            getRowId={(row) => row.team.id}
            labels={{ ...labels, empty: t("empty") }}
            loading={!data}
            searchText={(row) =>
              [row.team.name, ...row.members.map((person) => person.name)].join(
                " ",
              )
            }
            searchable
          />
          <details className="text-sm">
            <summary className="flex w-max cursor-pointer list-none items-center gap-1.5 font-medium [&::-webkit-details-marker]:hidden">
              <ChevronRightIcon
                aria-hidden="true"
                className="size-4 text-muted-foreground"
              />
              {t("hintTitle")}
            </summary>
            <p className="max-w-3xl pt-2 pl-6 text-muted-foreground">
              {t("hint")}
            </p>
          </details>
        </div>
      )}

      {data && editing ? (
        <TeamDialog
          finalFocus={returnTo}
          onOpenChange={(open) => (open ? undefined : setEditing(undefined))}
          onSaved={(team, created) => {
            setEditing(undefined);
            setNotice(t(created ? "created" : "saved", { name: team.name }));
            void load();
          }}
          people={data.people.filter((person) => person.active)}
          team={editing === "new" ? undefined : editing}
        />
      ) : null}
      {removing ? (
        <ConfirmDialog
          confirm={t("deleteConfirm")}
          description={t("deleteDescription")}
          destructive
          finalFocus={returnTo}
          onConfirm={async () => {
            try {
              await deleteTeam(removing.id);
              setRemoving(undefined);
              setNotice(t("deleted", { name: removing.name }));
              await load();
              return undefined;
            } catch (error) {
              return problemText(error, t("failed"), t("forbidden"));
            }
          }}
          onOpenChange={(open) => (open ? undefined : setRemoving(undefined))}
          open
          title={t("deleteTitle", { name: removing.name })}
        />
      ) : null}
    </PanelPage>
  );
}

function TeamDialog({
  team,
  people,
  onSaved,
  onOpenChange,
  finalFocus,
}: {
  team?: StaffTeam;
  people: Person[];
  onSaved: (team: StaffTeam, created: boolean) => void;
  onOpenChange: (open: boolean) => void;
  finalFocus: HTMLElement | null;
}) {
  const t = useTranslations("Teams");
  const common = useTranslations("Common");
  const [name, setName] = useState(team?.name ?? "");
  const [members, setMembers] = useState(new Set(team?.member_ids ?? []));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const sorted = [...people].sort((a, b) => collator.compare(a.name, b.name));

  async function save() {
    if (!name.trim()) {
      setProblem(t("nameRequired"));
      return;
    }
    setBusy(true);
    setProblem(undefined);
    try {
      const input = { name: name.trim(), member_ids: [...members] };
      const saved = team
        ? await updateTeam(team.id, input)
        : await createTeam(input);
      onSaved(saved, !team);
    } catch (error) {
      setProblem(problemText(error, t("failed"), t("forbidden")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent
        closeLabel={common("close")}
        finalFocus={() => finalFocus ?? true}
      >
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <DialogHeader>
            <DialogTitle>
              {team ? t("dialogEdit", { name: team.name }) : t("dialogNew")}
            </DialogTitle>
            <DialogDescription>{t("dialogDescription")}</DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="team-name">{t("name")}</FieldLabel>
              <Input
                id="team-name"
                maxLength={160}
                onChange={(event) => setName(event.target.value)}
                required
                value={name}
              />
            </Field>
            <FieldSet>
              <FieldLegend variant="label">{t("members")}</FieldLegend>
              <FieldDescription>{t("membersHint")}</FieldDescription>
              <div className="grid max-h-72 gap-2 overflow-y-auto sm:grid-cols-2">
                {sorted.map((person) => (
                  <label
                    className="flex items-center gap-2 text-sm"
                    key={person.id}
                  >
                    <input
                      checked={members.has(person.id)}
                      className="size-4"
                      onChange={(event) => {
                        const next = new Set(members);
                        if (event.target.checked) next.add(person.id);
                        else next.delete(person.id);
                        setMembers(next);
                      }}
                      type="checkbox"
                    />
                    <span>
                      {person.name}
                      {person.membership_id ? null : (
                        <span className="text-muted-foreground">
                          {" "}
                          · {t("noAccount")}
                        </span>
                      )}
                    </span>
                  </label>
                ))}
              </div>
            </FieldSet>
          </FieldGroup>
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DialogFooter>
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
