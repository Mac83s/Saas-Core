"use client";

import { useCallback, useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { CopyIcon, PencilIcon, PlusIcon } from "lucide-react";

import {
  copyBookingRulesToNextYear,
  createBookingRule,
  deleteBookingRule,
  listBookingRules,
  updateBookingRule,
  type BookingRule,
  type GroupSetup,
  type ResourceSetup,
  type ServiceSetup,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
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
import {
  Field,
  FieldDescription,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { PanelSection } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";
import { problemText } from "./people/person-dialogs";

const asDay = (value: string) => new Date(`${value}T12:00:00`);
/** 0 = Monday … 6 = Sunday, as the API counts them; 2024-01-01 was a Monday. */
const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6];
const weekdayDate = (day: number) => new Date(2024, 0, 1 + day, 12);

type Scope = `service:${string}` | `group:${string}` | `resource:${string}`;

const scopeOf = (rule: BookingRule): Scope | "" =>
  rule.service_id
    ? `service:${rule.service_id}`
    : rule.group_id
      ? `group:${rule.group_id}`
      : rule.resource_id
        ? `resource:${rule.resource_id}`
        : "";

/**
 * Sezony i zasady (ADR-072 §5): what a stay may be in a stretch of dates —
 * shortest and longest, arrival and departure days, how far ahead, or closed.
 * A unit's season goes before its group's, a group's before the offer's.
 */
export function SeasonsSection({
  groups,
  resources,
  services,
}: {
  groups: GroupSetup[];
  resources: ResourceSetup[];
  /** The offers booked by dates (`range`); a season acts on stays only. */
  services: ServiceSetup[];
}) {
  const t = useTranslations("ServicesSetup");
  const format = useFormatter();
  const labels = useDataTableLabels();
  const [items, setItems] = useState<BookingRule[]>();
  const [editing, setEditing] = useState<{ item?: BookingRule }>();
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<string>();

  const load = useCallback(async () => {
    try {
      setItems(await listBookingRules());
    } catch (error) {
      setProblem(problemText(error, t("failed"), t("forbidden")));
    }
  }, [t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    void load();
  }, [load]);

  const days = (item: BookingRule) =>
    format.dateTimeRange(asDay(item.starts_on), asDay(item.ends_on), {
      dateStyle: "medium",
    });
  const title = (item: BookingRule) => item.name || days(item);
  const weekdays = (list: number[]) =>
    list
      .map((day) => format.dateTime(weekdayDate(day), { weekday: "short" }))
      .join(", ");
  // Lengths count in the offer's own unit: nights, or days.
  const byDays = (item: BookingRule) => {
    const offers = item.service_id
      ? services.filter((service) => service.id === item.service_id)
      : item.group_id
        ? services.filter((service) =>
            service.group_ids.includes(item.group_id ?? ""),
          )
        : services;
    return offers.length > 0 && offers.every((o) => o.range_unit === "day");
  };
  const scopeName = (item: BookingRule) => {
    if (item.service_id)
      return t("appliesService", {
        name: services.find((x) => x.id === item.service_id)?.name ?? "—",
      });
    if (item.group_id)
      return t("appliesGroup", {
        name: groups.find((x) => x.id === item.group_id)?.name ?? "—",
      });
    return t("appliesUnit", {
      name: resources.find((x) => x.id === item.resource_id)?.name ?? "—",
    });
  };
  const rules = (item: BookingRule) => {
    if (item.closed) return [t("ruleClosed")];
    const unit = byDays(item) ? "Days" : "Nights";
    return [
      item.min_length !== null
        ? t(`ruleMin${unit}`, { count: item.min_length })
        : null,
      item.max_length !== null
        ? t(`ruleMax${unit}`, { count: item.max_length })
        : null,
      item.length_multiple !== null
        ? t("ruleMultiple", { count: item.length_multiple })
        : null,
      item.start_weekdays.length
        ? t("ruleStart", { days: weekdays(item.start_weekdays) })
        : null,
      item.end_weekdays.length
        ? t("ruleEnd", { days: weekdays(item.end_weekdays) })
        : null,
      item.notice_hours !== null
        ? t("ruleNotice", { count: item.notice_hours })
        : null,
      item.window_days !== null
        ? t("ruleWindow", { count: item.window_days })
        : null,
      item.buffer_after_minutes !== null
        ? t("ruleBuffer", { count: item.buffer_after_minutes })
        : null,
    ].filter((text): text is string => Boolean(text));
  };
  const latestYear = Math.max(
    0,
    ...(items ?? []).map((item) => Number(item.starts_on.slice(0, 4))),
  );

  async function remove(item: BookingRule) {
    setProblem(undefined);
    try {
      await deleteBookingRule(item.id, item.version, crypto.randomUUID());
      setNotice(t("seasonRemoved", { name: title(item) }));
    } catch (error) {
      setProblem(
        problemText(error, t("failed"), t("forbidden"), {
          booking_version_conflict: t("versionConflict"),
        }),
      );
    }
    void load();
  }

  async function copy() {
    setProblem(undefined);
    try {
      const count = await copyBookingRulesToNextYear(
        latestYear,
        crypto.randomUUID(),
      );
      setNotice(t("seasonsCopied", { count, year: latestYear + 1 }));
    } catch (error) {
      setProblem(problemText(error, t("failed"), t("forbidden")));
    }
    void load();
  }

  const columns: ColumnDef<BookingRule, unknown>[] = [
    {
      id: "season",
      accessorKey: "starts_on",
      header: t("colSeason"),
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <>
          <p className="font-medium wrap-anywhere">
            {title(item)}
            {item.active ? null : (
              <Badge className="ml-2" variant="outline">
                {t("seasonOff")}
              </Badge>
            )}
          </p>
          {item.name ? (
            <p className="text-sm text-muted-foreground">{days(item)}</p>
          ) : null}
        </>
      ),
    },
    {
      id: "scope",
      header: t("colAppliesTo"),
      enableSorting: false,
      cell: ({ row: { original: item } }) => scopeName(item),
    },
    {
      id: "rules",
      header: t("colRules"),
      enableSorting: false,
      cell: ({ row: { original: item } }) => {
        const said = rules(item);
        return said.length ? said.join(" · ") : t("ruleNone");
      },
    },
    {
      id: "actions",
      header: t("colActions"),
      enableSorting: false,
      meta: { actions: true },
      cell: ({ row: { original: item } }) => (
        <RowActions
          items={[
            {
              label: t("editFor", { name: title(item) }),
              icon: <PencilIcon aria-hidden="true" />,
              inline: true,
              main: true,
              onSelect: (trigger) => {
                setReturnTo(trigger ?? null);
                setEditing({ item });
              },
            },
            {
              label: t("removeSeason"),
              onSelect: () => void remove(item),
            },
          ]}
          label={t("actionsFor", { name: title(item) })}
        />
      ),
    },
  ];

  return (
    <PanelSection
      actions={
        <div className="flex flex-wrap gap-2">
          {latestYear ? (
            <Button onClick={() => void copy()} variant="outline">
              <CopyIcon aria-hidden="true" />
              {t("copySeasons", { from: latestYear, to: latestYear + 1 })}
            </Button>
          ) : null}
          <Button
            onClick={(event) => {
              setReturnTo(event.currentTarget);
              setEditing({});
            }}
            variant="outline"
          >
            <PlusIcon aria-hidden="true" />
            {t("addSeason")}
          </Button>
        </div>
      }
      description={t("seasonsHint")}
      title={t("seasonsTitle")}
    >
      <p className="text-sm text-success-foreground empty:hidden" role="status">
        {notice}
      </p>
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      <DataTable
        caption={t("seasonsCaption")}
        columns={columns}
        data={items ?? []}
        getRowId={(item) => item.id}
        labels={{ ...labels, empty: t("noSeasons") }}
        loading={!items}
      />
      {editing ? (
        <SeasonDialog
          finalFocus={returnTo}
          groups={groups.filter(
            (group) => group.active || group.id === editing.item?.group_id,
          )}
          item={editing.item}
          onOpenChange={(open) => {
            if (!open) {
              setEditing(undefined);
              void load();
            }
          }}
          onSaved={(saved, created) => {
            setEditing(undefined);
            setNotice(
              t(created ? "seasonAdded" : "seasonSaved", {
                name: title(saved),
              }),
            );
            void load();
          }}
          resources={resources.filter(
            (unit) => unit.active || unit.id === editing.item?.resource_id,
          )}
          services={services.filter(
            (offer) => offer.active || offer.id === editing.item?.service_id,
          )}
        />
      ) : null}
    </PanelSection>
  );
}

const number = (value: string) => (value.trim() === "" ? null : Number(value));
const text = (value: number | null | undefined) =>
  value === null || value === undefined ? "" : String(value);

function SeasonDialog({
  finalFocus,
  groups,
  item,
  onOpenChange,
  onSaved,
  resources,
  services,
}: {
  finalFocus: HTMLElement | null;
  groups: GroupSetup[];
  item?: BookingRule;
  onOpenChange: (open: boolean) => void;
  onSaved: (saved: BookingRule, created: boolean) => void;
  resources: ResourceSetup[];
  services: ServiceSetup[];
}) {
  const t = useTranslations("ServicesSetup");
  const common = useTranslations("Common");
  const format = useFormatter();
  const [name, setName] = useState(item?.name ?? "");
  const [scope, setScope] = useState<Scope | "">(
    item ? scopeOf(item) : services[0] ? `service:${services[0].id}` : "",
  );
  const [startsOn, setStartsOn] = useState(item?.starts_on ?? "");
  const [endsOn, setEndsOn] = useState(item?.ends_on ?? "");
  const [closed, setClosed] = useState(item?.closed ?? false);
  const [minLength, setMinLength] = useState(text(item?.min_length));
  const [maxLength, setMaxLength] = useState(text(item?.max_length));
  const [multiple, setMultiple] = useState(text(item?.length_multiple));
  const [starts, setStarts] = useState<number[]>(item?.start_weekdays ?? []);
  const [ends, setEnds] = useState<number[]>(item?.end_weekdays ?? []);
  const [notice, setNotice] = useState(text(item?.notice_hours));
  const [windowDays, setWindowDays] = useState(text(item?.window_days));
  const [buffer, setBuffer] = useState(text(item?.buffer_after_minutes));
  const [active, setActive] = useState(item?.active ?? true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [idempotencyKey] = useState(() => crypto.randomUUID());

  async function save() {
    if (!scope) {
      setProblem(t("seasonScopeRequired"));
      return;
    }
    if (!startsOn || !endsOn) {
      setProblem(t("seasonDatesRequired"));
      return;
    }
    if (endsOn < startsOn) {
      setProblem(t("seasonEndBeforeStart"));
      return;
    }
    const [kind, id] = scope.split(":") as [
      "service" | "group" | "resource",
      string,
    ];
    const body = {
      name: name.trim(),
      service_id: kind === "service" ? id : null,
      group_id: kind === "group" ? id : null,
      resource_id: kind === "resource" ? id : null,
      starts_on: startsOn,
      ends_on: endsOn,
      closed,
      min_length: closed ? null : number(minLength),
      max_length: closed ? null : number(maxLength),
      length_multiple: closed ? null : number(multiple),
      start_weekdays: closed ? [] : starts,
      end_weekdays: closed ? [] : ends,
      notice_hours: closed ? null : number(notice),
      window_days: closed ? null : number(windowDays),
      buffer_after_minutes: closed ? null : number(buffer),
      active,
    };
    setBusy(true);
    setProblem(undefined);
    try {
      onSaved(
        item
          ? await updateBookingRule(
              item.id,
              { ...body, expected_version: item.version },
              idempotencyKey,
            )
          : await createBookingRule(body, idempotencyKey),
        !item,
      );
    } catch (error) {
      setProblem(
        problemText(error, t("failed"), t("forbidden"), {
          booking_version_conflict: t("versionConflict"),
        }),
      );
    } finally {
      setBusy(false);
    }
  }

  const weekdayPicker = (
    legend: string,
    chosen: number[],
    choose: (days: number[]) => void,
    id: string,
  ) => (
    <FieldSet>
      <FieldLegend variant="label">{legend}</FieldLegend>
      <FieldDescription>{t("anyWeekday")}</FieldDescription>
      <div className="flex flex-wrap gap-x-4">
        {WEEKDAYS.map((day) => (
          <label
            className="flex min-h-11 items-center gap-2 text-sm"
            htmlFor={`${id}-${day}`}
            key={day}
          >
            <input
              checked={chosen.includes(day)}
              className="size-4"
              id={`${id}-${day}`}
              onChange={(event) =>
                choose(
                  event.target.checked
                    ? [...chosen, day].sort()
                    : chosen.filter((other) => other !== day),
                )
              }
              type="checkbox"
            />
            {format.dateTime(weekdayDate(day), { weekday: "short" })}
          </label>
        ))}
      </div>
    </FieldSet>
  );

  const numberField = (
    id: string,
    label: string,
    value: string,
    change: (value: string) => void,
    min: number,
  ) => (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        id={id}
        inputMode="numeric"
        min={min}
        onChange={(event) => change(event.target.value)}
        type="number"
        value={value}
      />
    </Field>
  );

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent
        className="sm:max-w-2xl"
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
              {t(item ? "editSeasonTitle" : "newSeasonTitle")}
            </DialogTitle>
            <DialogDescription>{t("seasonHint")}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="season-name">{t("seasonName")}</FieldLabel>
              <Input
                autoComplete="off"
                id="season-name"
                maxLength={160}
                onChange={(event) => setName(event.target.value)}
                value={name}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="season-scope">{t("appliesTo")}</FieldLabel>
              <NativeSelect
                id="season-scope"
                onChange={(event) => setScope(event.target.value as Scope)}
                value={scope}
              >
                {services.length ? (
                  <optgroup label={t("scopeOffers")}>
                    {services.map((offer) => (
                      <option key={offer.id} value={`service:${offer.id}`}>
                        {offer.name}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
                {groups.length ? (
                  <optgroup label={t("scopeGroups")}>
                    {groups.map((group) => (
                      <option key={group.id} value={`group:${group.id}`}>
                        {group.name}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
                {resources.length ? (
                  <optgroup label={t("scopeUnits")}>
                    {resources.map((unit) => (
                      <option key={unit.id} value={`resource:${unit.id}`}>
                        {unit.name}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
              </NativeSelect>
            </Field>
            <Field>
              <FieldLabel htmlFor="season-from">{t("seasonFrom")}</FieldLabel>
              <Input
                id="season-from"
                onChange={(event) => setStartsOn(event.target.value)}
                type="date"
                value={startsOn}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="season-to">{t("seasonTo")}</FieldLabel>
              <Input
                id="season-to"
                onChange={(event) => setEndsOn(event.target.value)}
                type="date"
                value={endsOn}
              />
            </Field>
          </div>
          <label
            className="flex min-h-11 items-center gap-2 text-sm"
            htmlFor="season-closed"
          >
            <input
              checked={closed}
              className="size-4"
              id="season-closed"
              onChange={(event) => setClosed(event.target.checked)}
              type="checkbox"
            />
            {t("seasonClosed")}
          </label>
          {closed ? null : (
            <>
              <p className="text-sm text-muted-foreground">
                {t("seasonLengthHint")}
              </p>
              <div className="grid gap-4 sm:grid-cols-3">
                {numberField(
                  "season-min",
                  t("minLength"),
                  minLength,
                  setMinLength,
                  1,
                )}
                {numberField(
                  "season-max",
                  t("maxLength"),
                  maxLength,
                  setMaxLength,
                  1,
                )}
                {numberField(
                  "season-multiple",
                  t("lengthMultiple"),
                  multiple,
                  setMultiple,
                  1,
                )}
              </div>
              {weekdayPicker(t("startWeekdays"), starts, setStarts, "arrive")}
              {weekdayPicker(t("endWeekdays"), ends, setEnds, "leave")}
              <div className="grid gap-4 sm:grid-cols-3">
                {numberField(
                  "season-notice",
                  t("noticeHours"),
                  notice,
                  setNotice,
                  0,
                )}
                {numberField(
                  "season-window",
                  t("windowDays"),
                  windowDays,
                  setWindowDays,
                  1,
                )}
                {numberField(
                  "season-buffer",
                  t("seasonBufferAfter"),
                  buffer,
                  setBuffer,
                  0,
                )}
              </div>
            </>
          )}
          {item ? (
            <label
              className="flex min-h-11 items-center gap-2 text-sm"
              htmlFor="season-active"
            >
              <input
                checked={active}
                className="size-4"
                id="season-active"
                onChange={(event) => setActive(event.target.checked)}
                type="checkbox"
              />
              {t("seasonActive")}
            </label>
          ) : null}
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>
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
