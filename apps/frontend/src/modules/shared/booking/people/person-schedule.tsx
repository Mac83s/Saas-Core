"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { CalendarOffIcon, PlusIcon, Trash2Icon } from "lucide-react";

import {
  getPerson,
  removeTimeOff,
  setPersonHours,
  type BookingCatalog,
  type Person,
  type PersonDetail,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { PanelSection } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";
import { problemText, TimeOffDialog } from "./person-dialogs";

type Range = { start: string; end: string; locationId: string };
type Week = Range[][];

const WEEK = [0, 1, 2, 3, 4, 5, 6];

function weekOf(detail: Pick<PersonDetail, "hours">): Week {
  return WEEK.map((day) =>
    detail.hours
      .filter((rule) => rule.weekday === day)
      .map((rule) => ({
        start: rule.local_start.slice(0, 5),
        end: rule.local_end.slice(0, 5),
        locationId: rule.location_id,
      })),
  );
}

/**
 * The card's "Grafik" page: the week the calendar offers the person for, and
 * the days they are away. Management edits both; the person their own where
 * the product lets them (owner's answer 7). A change moves no booked visit.
 */
export function PersonSchedule({
  detail,
  catalog,
  people,
  canEdit,
  zone,
  today,
  onChanged,
  onNotice,
}: {
  detail: PersonDetail;
  catalog?: BookingCatalog;
  /** Others with hours, for "Kopiuj od…"; empty without the team screen. */
  people: Person[];
  canEdit: boolean;
  zone: string;
  today: string;
  onChanged: (detail: PersonDetail) => void;
  onNotice: (text: string) => void;
}) {
  const t = useTranslations("PersonCard");
  const people18n = useTranslations("People");
  const labels = useDataTableLabels();
  const format = useFormatter();
  const locations = catalog?.locations ?? [];
  const fallbackPlace = locations[0]?.id ?? "";
  const [week, setWeek] = useState<Week>(() => weekOf(detail));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [adding, setAdding] = useState(false);
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);
  const others = people.filter(
    (person) => person.id !== detail.id && person.active && person.has_hours,
  );

  const change = (day: number, ranges: Range[]) =>
    setWeek(week.map((item, index) => (index === day ? ranges : item)));

  async function save() {
    setBusy(true);
    setProblem(undefined);
    try {
      const saved = await setPersonHours(
        detail.id,
        week.flatMap((ranges, weekday) =>
          ranges.map((range) => ({
            weekday,
            local_start: range.start,
            local_end: range.end,
            location_id: range.locationId || fallbackPlace,
          })),
        ),
      );
      setWeek(weekOf(saved));
      onChanged(saved);
      onNotice(t("hoursSaved"));
    } catch (error) {
      setProblem(
        problemText(error, people18n("failed"), people18n("forbidden")),
      );
    } finally {
      setBusy(false);
    }
  }

  async function copy(staffId: string) {
    if (!staffId) return;
    setProblem(undefined);
    try {
      setWeek(weekOf(await getPerson(staffId)));
    } catch (error) {
      setProblem(
        problemText(error, people18n("failed"), people18n("forbidden")),
      );
    }
  }

  const dateTime = (value: string) =>
    format.dateTime(new Date(value), {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: zone,
    });
  const timeOffColumns: ColumnDef<PersonDetail["time_off"][number], unknown>[] =
    [
      {
        id: "from",
        accessorKey: "starts_at",
        header: t("timeOffFrom"),
        meta: { primary: true },
        cell: ({ row: { original: item } }) => dateTime(item.starts_at),
      },
      {
        id: "to",
        accessorKey: "ends_at",
        header: t("timeOffTo"),
        cell: ({ row: { original: item } }) => dateTime(item.ends_at),
      },
      {
        id: "reason",
        header: t("timeOffReason"),
        enableSorting: false,
        cell: ({ row: { original: item } }) => item.reason || "—",
      },
      {
        id: "actions",
        header: t("actions"),
        meta: { actions: true },
        cell: ({ row: { original: item } }) =>
          canEdit ? (
            <RowActions
              items={[
                {
                  label: t("timeOffRemove"),
                  icon: <Trash2Icon aria-hidden="true" />,
                  inline: true,
                  destructive: true,
                  onSelect: async () => {
                    setProblem(undefined);
                    try {
                      await removeTimeOff(item.id);
                      onChanged({
                        ...detail,
                        time_off: detail.time_off.filter(
                          (other) => other.id !== item.id,
                        ),
                      });
                      onNotice(t("timeOffRemoved"));
                    } catch (error) {
                      setProblem(
                        problemText(
                          error,
                          people18n("failed"),
                          people18n("forbidden"),
                        ),
                      );
                    }
                  },
                },
              ]}
              label={t("timeOffActions", { from: dateTime(item.starts_at) })}
            />
          ) : null,
      },
    ];

  return (
    <div className="space-y-8">
      <PanelSection
        actions={
          canEdit && others.length ? (
            <div className="flex items-center gap-2">
              <label
                className="text-sm text-muted-foreground"
                htmlFor="hours-copy"
              >
                {t("copyFrom")}
              </label>
              <NativeSelect
                className="w-48"
                id="hours-copy"
                onChange={(event) => void copy(event.target.value)}
                value=""
              >
                <option value="">{t("copyChoose")}</option>
                {others.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name}
                  </option>
                ))}
              </NativeSelect>
            </div>
          ) : null
        }
        description={t("hoursDescription")}
        title={t("hoursTitle")}
      >
        <ul className="divide-y rounded-xl border">
          {WEEK.map((day) => {
            const ranges = week[day];
            return (
              <li
                className="grid gap-2 p-3 sm:grid-cols-[8rem_1fr] sm:items-start"
                key={day}
              >
                <p className="pt-2 font-medium">
                  {people18n(`dayLong_${day}`)}
                </p>
                <div className="space-y-2">
                  {ranges.length === 0 ? (
                    <p className="pt-2 text-sm text-muted-foreground">
                      {t("dayOff")}
                    </p>
                  ) : null}
                  {ranges.map((range, index) => {
                    const id = `hours-${day}-${index}`;
                    const set = (patch: Partial<Range>) =>
                      change(
                        day,
                        ranges.map((item, position) =>
                          position === index ? { ...item, ...patch } : item,
                        ),
                      );
                    return (
                      <div
                        className="flex flex-wrap items-center gap-2"
                        key={id}
                      >
                        <label className="sr-only" htmlFor={`${id}-from`}>
                          {t("rangeFrom", {
                            day: people18n(`dayLong_${day}`),
                          })}
                        </label>
                        <Input
                          className="w-32"
                          disabled={!canEdit}
                          id={`${id}-from`}
                          onChange={(event) =>
                            set({ start: event.target.value })
                          }
                          type="time"
                          value={range.start}
                        />
                        <span aria-hidden="true">–</span>
                        <label className="sr-only" htmlFor={`${id}-to`}>
                          {t("rangeTo", { day: people18n(`dayLong_${day}`) })}
                        </label>
                        <Input
                          className="w-32"
                          disabled={!canEdit}
                          id={`${id}-to`}
                          onChange={(event) => set({ end: event.target.value })}
                          type="time"
                          value={range.end}
                        />
                        {locations.length > 1 ? (
                          <>
                            <label className="sr-only" htmlFor={`${id}-place`}>
                              {t("rangePlace", {
                                day: people18n(`dayLong_${day}`),
                              })}
                            </label>
                            <NativeSelect
                              className="w-44"
                              disabled={!canEdit}
                              id={`${id}-place`}
                              onChange={(event) =>
                                set({ locationId: event.target.value })
                              }
                              value={range.locationId || fallbackPlace}
                            >
                              {locations.map((location) => (
                                <option key={location.id} value={location.id}>
                                  {location.name}
                                </option>
                              ))}
                            </NativeSelect>
                          </>
                        ) : null}
                        {canEdit ? (
                          <Button
                            aria-label={t("rangeRemove", {
                              day: people18n(`dayLong_${day}`),
                            })}
                            onClick={() =>
                              change(
                                day,
                                ranges.filter(
                                  (_, position) => position !== index,
                                ),
                              )
                            }
                            size="icon"
                            type="button"
                            variant="ghost"
                          >
                            <Trash2Icon aria-hidden="true" />
                          </Button>
                        ) : null}
                      </div>
                    );
                  })}
                  {canEdit && fallbackPlace ? (
                    <Button
                      onClick={() =>
                        change(day, [
                          ...ranges,
                          {
                            start: ranges.at(-1)?.end ?? "08:00",
                            end: "16:00",
                            locationId:
                              ranges.at(-1)?.locationId ?? fallbackPlace,
                          },
                        ])
                      }
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      <PlusIcon aria-hidden="true" />
                      {t("rangeAdd", { day: people18n(`dayLong_${day}`) })}
                    </Button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
        {canEdit ? (
          fallbackPlace ? (
            <Button disabled={busy} onClick={() => void save()}>
              {t("hoursSave")}
            </Button>
          ) : (
            <p className="text-sm text-muted-foreground">
              {people18n("visitsSetupFirst")}
            </p>
          )
        ) : null}
      </PanelSection>

      <PanelSection
        actions={
          canEdit ? (
            <Button
              onClick={(event) => {
                setReturnTo(event.currentTarget);
                setAdding(true);
              }}
              variant="outline"
            >
              <CalendarOffIcon aria-hidden="true" />
              {t("timeOffAdd")}
            </Button>
          ) : null
        }
        description={t("timeOffDescription")}
        title={t("timeOffTitle")}
      >
        <DataTable
          caption={t("timeOffCaption", { name: detail.name })}
          columns={timeOffColumns}
          data={detail.time_off}
          getRowId={(item) => item.id}
          labels={{ ...labels, empty: t("timeOffNone") }}
        />
      </PanelSection>

      {adding ? (
        <TimeOffDialog
          finalFocus={returnTo}
          name={detail.name}
          onAdded={(result) => {
            setAdding(false);
            onChanged({
              ...detail,
              time_off: [...detail.time_off, result.time_off].sort((a, b) =>
                a.starts_at.localeCompare(b.starts_at),
              ),
            });
            onNotice(
              result.conflicts
                ? people18n("timeOffConflicts", {
                    name: detail.name,
                    count: result.conflicts,
                  })
                : people18n("timeOffAdded", { name: detail.name }),
            );
          }}
          onOpenChange={setAdding}
          open
          staffId={detail.id}
          today={today}
          zone={zone}
        />
      ) : null}
    </div>
  );
}
