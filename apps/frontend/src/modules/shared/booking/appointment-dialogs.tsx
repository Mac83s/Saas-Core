"use client";

import {
  Fragment,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type RefObject,
} from "react";
import { useLocale, useTranslations } from "next-intl";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  CalendarCheckIcon,
  CheckCircle2Icon,
  CircleIcon,
  UserXIcon,
  XCircleIcon,
  XIcon,
  type LucideIcon,
} from "lucide-react";

import {
  ApiProblemError,
  cancelBookingAppointment,
  completeBookingAppointment,
  createBookingAppointment,
  getBookingSlots,
  rescheduleBookingAppointment,
  setBookingAppointmentMaterials,
  type BookingAppointment,
  type BookingCatalog,
  type BookingSlotList,
  type StaffTeam,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Textarea } from "@saas-core/ui/components/textarea";
import { cn } from "@saas-core/ui/lib/utils";

import {
  addDays,
  dateFormat,
  formatWhen,
  wallClock,
  zonedInstant,
} from "./calendar-time";
import { CrewDialog } from "./dispatch/crew-dialog";
import {
  draftsOf,
  materialsInput,
  MaterialsEditor,
  MaterialsList,
  useWarehouse,
  type MaterialDraft,
} from "./materials-editor";

type Slot = BookingSlotList["items"][number];
type Translate = ReturnType<typeof useTranslations>;
/** Where focus goes when a dialog closes (Base UI `finalFocus`). */
type FocusTarget = () => HTMLElement | boolean | null;

/** Colour, icon and text together: status is never told by colour alone. */
const STATUS_STYLES: Record<
  string,
  { className: string; border: string; icon: LucideIcon }
> = {
  confirmed: {
    className: "bg-info text-info-foreground",
    border: "border-l-info-foreground",
    icon: CalendarCheckIcon,
  },
  completed: {
    className: "bg-success text-success-foreground",
    border: "border-l-success-foreground",
    icon: CheckCircle2Icon,
  },
  no_show: {
    className: "bg-warning text-warning-foreground",
    border: "border-l-warning-foreground",
    icon: UserXIcon,
  },
  canceled: {
    className: "bg-muted text-muted-foreground",
    border: "border-l-muted-foreground",
    icon: XCircleIcon,
  },
};

export const STATUSES = Object.keys(STATUS_STYLES);

export function statusStyle(status: string) {
  return (
    STATUS_STYLES[status] ?? {
      className: "border-border bg-background text-foreground",
      border: "border-l-border",
      icon: CircleIcon,
    }
  );
}

export function statusLabel(t: Translate, status: string): string {
  return t.has(`status.${status}`) ? t(`status.${status}`) : status;
}

export function StatusBadge({ status }: { status: string }) {
  const t = useTranslations("Calendar");
  const { className, icon: Icon } = statusStyle(status);
  return (
    <Badge className={className}>
      <Icon aria-hidden="true" />
      {statusLabel(t, status)}
    </Badge>
  );
}

function problemText(error: unknown, t: Translate, fallback: string) {
  switch (error instanceof ApiProblemError ? error.problem.code : "") {
    case "slot_unavailable":
      return t("slotTaken");
    case "appointment_not_changeable":
      return t("notChangeable");
    case "entitlement_required":
      return t("notInPlan");
    case "organization_permission_denied":
      return t("noAccess");
    default:
      return t(fallback);
  }
}

type SlotSearch = { slots?: Slot[]; loading?: boolean; failed?: boolean };

/**
 * Free times for the week starting at `day`: the day's own and, when it is
 * full, the next free one. The window starts at the chosen day on purpose:
 * the API stops at 250 results, and the chosen day must not be the part cut.
 */
function useFreeSlots(
  serviceId: string,
  locationId: string,
  day: string,
  version = 0,
): SlotSearch {
  const key =
    serviceId && locationId && /^\d{4}-\d{2}-\d{2}$/.test(day)
      ? [serviceId, locationId, day, version].join("|")
      : "";
  const [result, setResult] = useState<{ key: string; slots?: Slot[] }>();
  useEffect(() => {
    if (!key) return;
    let current = true;
    getBookingSlots({
      service_id: serviceId,
      location_id: locationId,
      from: day,
      to: addDays(day, 6),
    })
      .then((value) => {
        if (current) setResult({ key, slots: value.items });
      })
      .catch(() => {
        if (current) setResult({ key });
      });
    return () => {
      current = false;
    };
  }, [key, serviceId, locationId, day]);
  if (!key) return {};
  if (result?.key !== key) return { loading: true };
  return result.slots ? { slots: result.slots } : { failed: true };
}

function findSlot(
  slots: Slot[] | undefined,
  day: string,
  time: string,
  zone: string,
) {
  return slots?.find((slot) => {
    const local = wallClock(slot.starts_at, zone);
    return local.day === day && local.time === time;
  });
}

const minutes = (time: string) =>
  Number(time.slice(0, 2)) * 60 + Number(time.slice(3, 5));

/**
 * One slot per start at which the visit's people are free (ADR-058 §5): every
 * one of `crew` when the office named them, else any `need` of those free. A
 * named crew's slot carries a resource free for all of them — the visit takes
 * one — and `resource`, when given, is the only one that counts.
 */
export function crewSlots(
  slots: Slot[] | undefined,
  crew: string[],
  need: number,
  resource?: string | null,
): Slot[] | undefined {
  if (!slots) return undefined;
  const starts = new Map<string, Slot[]>();
  for (const slot of slots) {
    if (resource !== undefined && slot.resource_id !== resource) continue;
    const list = starts.get(slot.starts_at);
    if (list) list.push(slot);
    else starts.set(slot.starts_at, [slot]);
  }
  const result: Slot[] = [];
  for (const list of starts.values()) {
    const match = crew.length
      ? list.find(
          (slot) =>
            slot.staff_id === crew[0] &&
            crew.every((id) =>
              list.some(
                (other) =>
                  other.staff_id === id &&
                  other.resource_id === slot.resource_id,
              ),
            ),
        )
      : new Set(list.map((slot) => slot.staff_id)).size >= need
        ? list[0]
        : undefined;
    if (match) result.push(match);
  }
  return result;
}

/**
 * Says before saving whether the chosen time is free, and offers the free
 * times nearest to it — or the next free day's first time. With `crew`, a
 * free time names who it is free for and offers the crew's other common times.
 */
function SlotHint({
  crew,
  day,
  idle,
  onPick,
  search,
  slots,
  time,
  zone,
}: {
  /** The names of the people the times were checked for together. */
  crew?: string[];
  day: string;
  idle: string;
  onPick: (slot: Slot) => void;
  search: SlotSearch;
  /** The search's slots narrowed to the staff member and resource needed. */
  slots?: Slot[];
  time: string;
  zone: string;
}) {
  const t = useTranslations("Calendar");
  const locale = useLocale();
  const messageId = useId();
  const othersId = useId();
  const match = findSlot(slots, day, time, zone);
  // One chip per start time, even when several people are free at it.
  const dayFree = (slots ?? []).filter(
    (slot, index, all) =>
      wallClock(slot.starts_at, zone).day === day &&
      all.findIndex((other) => other.starts_at === slot.starts_at) === index,
  );
  const next = slots?.find((slot) => wallClock(slot.starts_at, zone).day > day);
  const others =
    match && crew?.length
      ? (slots ?? [])
          .filter(
            (slot, index, all) =>
              slot.starts_at !== match.starts_at &&
              wallClock(slot.starts_at, zone).day >= day &&
              all.findIndex((other) => other.starts_at === slot.starts_at) ===
                index,
          )
          .slice(0, 4)
      : [];

  let message = idle;
  let tone = "text-muted-foreground";
  let chips: Slot[] = [];
  if (search.loading) message = t("slotsLoading");
  else if (search.failed) {
    message = t("slotsError");
    tone = "text-destructive";
  } else if (!slots) message = idle;
  else if (match) {
    message = crew?.length
      ? t("slotFreeFor", { names: crew.join(", ") })
      : t("slotFree");
    tone = "text-success-foreground";
  } else if (dayFree.length) {
    message = time ? t("slotBusy") : t("freeTimes");
    tone = time ? "text-warning-foreground" : tone;
    const target = time ? minutes(time) : 0;
    const distance = (slot: Slot) =>
      Math.abs(minutes(wallClock(slot.starts_at, zone).time) - target);
    chips = [...dayFree]
      .sort((a, b) => distance(a) - distance(b))
      .slice(0, 8)
      .sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at));
  } else if (next) {
    message = t("noFreeDay");
    chips = [next];
  } else message = t("noFreeWeek");

  const label = (slot: Slot) =>
    dateFormat(locale, {
      ...(wallClock(slot.starts_at, zone).day === day
        ? {}
        : { weekday: "short", day: "numeric", month: "short" }),
      hour: "2-digit",
      minute: "2-digit",
      timeZone: zone,
    }).format(new Date(slot.starts_at));

  const group = (items: Slot[], labelledBy: string) => (
    <div
      aria-labelledby={labelledBy}
      className="flex flex-wrap gap-2"
      role="group"
    >
      {items.map((slot) => (
        <Button
          className="px-3 tabular-nums"
          key={slot.starts_at}
          onClick={() => onPick(slot)}
          type="button"
          variant="outline"
        >
          {label(slot)}
        </Button>
      ))}
    </div>
  );

  return (
    <div className="space-y-2 rounded-lg border bg-muted/40 p-3">
      <p aria-live="polite" className={cn("text-sm", tone)} id={messageId}>
        {message}
      </p>
      {chips.length ? group(chips, messageId) : null}
      {others.length ? (
        <>
          <p className="text-sm text-muted-foreground" id={othersId}>
            {t(crew && crew.length > 1 ? "otherCommonTimes" : "otherFreeTimes")}
          </p>
          {group(others, othersId)}
        </>
      ) : null}
    </div>
  );
}

type NewValues = {
  service_id: string;
  location_id: string;
  date: string;
  time: string;
  display_name: string;
  email: string;
  phone: string;
  notes: string;
};

export function NewAppointmentDialog({
  canUseInventory = false,
  catalog,
  day,
  staffId = "",
  onCreated,
  onOpenChange,
  open,
  restoreFocus,
  teams = [],
  zone,
}: {
  canUseInventory?: boolean;
  catalog: BookingCatalog;
  /** The day the calendar shows; the form starts there unless it is past. */
  day: string;
  /** The person the calendar is filtered to: the form starts with them. */
  staffId?: string;
  onCreated: (appointment: BookingAppointment) => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  restoreFocus: FocusTarget;
  /** The company's teams: choosing one names its members at once. */
  teams?: StaffTeam[];
  zone: string;
}) {
  const t = useTranslations("Calendar");
  const common = useTranslations("Common");
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-2xl"
        closeLabel={common("close")}
        finalFocus={restoreFocus}
      >
        <DialogHeader>
          <DialogTitle>{t("createTitle")}</DialogTitle>
          <DialogDescription>{t("createDescription")}</DialogDescription>
        </DialogHeader>
        <NewAppointmentForm
          canUseInventory={canUseInventory}
          catalog={catalog}
          day={day}
          onCreated={onCreated}
          staffId={staffId}
          teams={teams}
          zone={zone}
        />
      </DialogContent>
    </Dialog>
  );
}

function NewAppointmentForm({
  canUseInventory,
  catalog,
  day,
  onCreated,
  staffId: chosenStaff,
  teams,
  zone,
}: {
  canUseInventory: boolean;
  catalog: BookingCatalog;
  day: string;
  onCreated: (appointment: BookingAppointment) => void;
  staffId: string;
  teams: StaffTeam[];
  zone: string;
}) {
  const t = useTranslations("Calendar");
  const common = useTranslations("Common");
  const locale = useLocale();
  const today = wallClock(new Date(), zone).day;
  // One key per opened form: a retry after a lost response gets the visit
  // already booked back instead of booking a second one.
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [version, setVersion] = useState(0);
  const [problem, setProblem] = useState<string>();
  // Who does it, the lead first; nobody named = the server picks (ADR-058 §4).
  const [crew, setCrew] = useState<string[]>(() =>
    catalog.staff.some((item) => item.id === chosenStaff) ? [chosenStaff] : [],
  );
  const [fromTeam, setFromTeam] = useState("");
  const schema = useMemo(
    () =>
      z
        .object({
          service_id: z.string().min(1, t("required")),
          location_id: z.string().min(1, t("required")),
          date: z.string().min(1, t("required")),
          time: z.string().min(1, t("required")),
          display_name: z.string().trim().min(1, t("required")).max(160),
          email: z.union([z.literal(""), z.email(t("invalidEmail"))]),
          phone: z.string().trim().max(40),
          notes: z.string().trim().max(500, t("notesTooLong")),
        })
        .refine((values) => values.email || values.phone, {
          message: t("contactRequired"),
          path: ["phone"],
        }),
    [t],
  );
  const only = (items: { id: string }[]) =>
    items.length === 1 ? items[0].id : "";
  const form = useForm<NewValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      service_id: only(catalog.services),
      location_id: only(catalog.locations),
      date: day < today ? today : day,
      time: "",
      display_name: "",
      email: "",
      phone: "",
      notes: "",
    },
  });
  const [serviceId, locationId, date, time] = useWatch({
    control: form.control,
    name: ["service_id", "location_id", "date", "time"],
  });
  const search = useFreeSlots(serviceId, locationId, date, version);
  const materials = useTranslations("BookingMaterials");
  const warehouse = useWarehouse(canUseInventory);
  // The service's products until somebody edits them; then exactly what they typed.
  const [edited, setEdited] = useState<MaterialDraft[]>();
  const chosen = catalog.services.find((one) => one.id === serviceId);
  // Its module takes the material itself (ADR-055): the calendar offers none.
  const takesMaterials = canUseInventory && chosen?.takes_materials !== false;
  const drafts = edited ?? draftsOf(chosen?.materials);
  const need = chosen?.staff_count ?? 1;
  const slots = crewSlots(search.slots, crew, need);
  const names = new Map(catalog.staff.map((item) => [item.id, item.name]));
  // Who the search found free at the chosen time: the add list says so.
  const freeNow = new Set(
    (search.slots ?? [])
      .filter((slot) => {
        const local = wallClock(slot.starts_at, zone);
        return local.day === date && local.time === time;
      })
      .map((slot) => slot.staff_id),
  );
  const checked = Boolean(time && search.slots);
  const errors = form.formState.errors;

  function pick(slot: Slot) {
    const local = wallClock(slot.starts_at, zone);
    form.setValue("date", local.day);
    form.setValue("time", local.time);
    form.clearErrors("time");
    form.setFocus("time");
  }

  function add(value: string) {
    const team = teams.find((item) => `team:${item.id}` === value);
    if (!team) {
      if (!crew.includes(value)) setCrew([...crew, value]);
      setFromTeam("");
      return;
    }
    // A team is the crew: as many of its people as the service needs, the
    // ones free at the chosen time first.
    const members = team.member_ids
      .filter((id) => names.has(id))
      .sort((a, b) => Number(freeNow.has(b)) - Number(freeNow.has(a)));
    setCrew(members.slice(0, need));
    setFromTeam(team.name);
  }

  function remove(id: string) {
    const next = crew.filter((item) => item !== id);
    setCrew(next);
    if (!next.length) setFromTeam("");
  }

  async function submit(values: NewValues) {
    // Named people book with a resource free for all of them: the API accepts
    // only people and a resource free at that instant. Nobody named names
    // neither — the server picks the least busy (ADR-058 §4).
    const slot = findSlot(slots, values.date, values.time, zone);
    if (!slot) {
      form.setError("time", { message: t("pickFreeTime") });
      return;
    }
    setProblem(undefined);
    const notes = values.notes.trim();
    try {
      onCreated(
        await createBookingAppointment(
          {
            service_id: values.service_id,
            location_id: values.location_id,
            ...(crew.length
              ? { staff_ids: crew, resource_id: slot.resource_id }
              : {}),
            starts_at: slot.starts_at,
            customer: {
              display_name: values.display_name.trim(),
              email: values.email,
              phone: values.phone.trim(),
              locale: locale === "en" ? "en" : "pl",
            },
            ...(notes ? { customer_notes: notes } : {}),
            ...(edited && takesMaterials
              ? { materials: materialsInput(edited) }
              : {}),
          },
          idempotencyKey,
        ),
      );
    } catch (error) {
      if (
        error instanceof ApiProblemError &&
        error.problem.code === "slot_unavailable"
      )
        setVersion((value) => value + 1);
      setProblem(problemText(error, t, "createError"));
    }
  }

  return (
    <form className="space-y-6" noValidate onSubmit={form.handleSubmit(submit)}>
      <FieldSet>
        <FieldLegend>{t("serviceAndPlace")}</FieldLegend>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field data-invalid={Boolean(errors.service_id)}>
            <FieldLabel htmlFor="appointment-service">
              {t("service")}
            </FieldLabel>
            <NativeSelect
              aria-invalid={Boolean(errors.service_id)}
              id="appointment-service"
              {...form.register("service_id")}
            >
              <option value="">{t("choose")}</option>
              {catalog.services.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </NativeSelect>
            {need > 1 ? (
              <FieldDescription>
                {t("serviceNeeds", { count: need })}
              </FieldDescription>
            ) : null}
            <FieldError errors={[errors.service_id]} />
          </Field>
          {/* One place needs no question; the form picks it. */}
          {catalog.locations.length > 1 ? (
            <Field data-invalid={Boolean(errors.location_id)}>
              <FieldLabel htmlFor="appointment-location">
                {t("location")}
              </FieldLabel>
              <NativeSelect
                aria-invalid={Boolean(errors.location_id)}
                id="appointment-location"
                {...form.register("location_id")}
              >
                <option value="">{t("choose")}</option>
                {catalog.locations.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </NativeSelect>
              <FieldError errors={[errors.location_id]} />
            </Field>
          ) : null}
        </div>
      </FieldSet>
      {/* One person needs no question either: the server takes them. */}
      {catalog.staff.length > 1 ? (
        <FieldSet>
          <FieldLegend>{t("crewLegend")}</FieldLegend>
          {fromTeam ? (
            <p className="text-sm">{t("crewFromTeam", { team: fromTeam })}</p>
          ) : null}
          {crew.length ? (
            <ul aria-label={t("crewChosen")} className="flex flex-wrap gap-2">
              {crew.map((id, index) => {
                const name = names.get(id) ?? id;
                return (
                  <li
                    className="flex items-center gap-1 rounded-lg border bg-muted/40 py-0.5 pr-0.5 pl-2 text-sm"
                    key={id}
                  >
                    {/* The ring picks who leads, as in „Zmień osoby”. */}
                    <label className="flex items-center gap-1.5 pointer-coarse:min-h-11">
                      <input
                        aria-label={t("crewLeadFor", { name })}
                        checked={index === 0}
                        className="size-4"
                        name="appointment-lead"
                        onChange={() =>
                          setCrew([id, ...crew.filter((item) => item !== id)])
                        }
                        type="radio"
                      />
                      {index === 0 ? (
                        <span
                          aria-hidden="true"
                          className="text-xs font-semibold"
                        >
                          {t("crewLeadShort")}
                        </span>
                      ) : null}
                      <span className="pr-1">{name}</span>
                    </label>
                    <Button
                      aria-label={t("crewRemoveFor", { name })}
                      className="pointer-coarse:size-11"
                      onClick={() => remove(id)}
                      size="icon-xs"
                      type="button"
                      variant="ghost"
                    >
                      <XIcon aria-hidden="true" />
                    </Button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-sm">{t("crewAutoOn")}</p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <NativeSelect
              aria-label={t("crewAdd")}
              onChange={(event) => {
                if (event.target.value) add(event.target.value);
              }}
              value=""
            >
              <option value="">{t("crewAdd")}</option>
              {teams.length ? (
                <optgroup label={t("crewTeams")}>
                  {teams.map((item) => (
                    <option key={item.id} value={`team:${item.id}`}>
                      {t("crewTeamOption", {
                        name: item.name,
                        count: item.member_ids.length,
                      })}
                    </option>
                  ))}
                </optgroup>
              ) : null}
              <optgroup label={t("crewPeople")}>
                {catalog.staff
                  .filter((item) => !crew.includes(item.id))
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {checked
                        ? t(
                            freeNow.has(item.id) ? "crewFreeAt" : "crewBusyAt",
                            {
                              name: item.name,
                              time,
                            },
                          )
                        : item.name}
                    </option>
                  ))}
              </optgroup>
            </NativeSelect>
            {crew.length ? (
              <Button
                onClick={() => {
                  setCrew([]);
                  setFromTeam("");
                }}
                type="button"
                variant="outline"
              >
                {t("crewAuto")}
              </Button>
            ) : null}
          </div>
          <FieldDescription>{t("crewAutoHint")}</FieldDescription>
          {crew.length && crew.length < need ? (
            <p className="text-sm text-warning-foreground">
              {t("crewShort", { count: need - crew.length })}
            </p>
          ) : null}
        </FieldSet>
      ) : null}
      <FieldSet>
        <FieldLegend>{t("when")}</FieldLegend>
        <div className="grid grid-cols-2 gap-4 sm:max-w-sm">
          <Field data-invalid={Boolean(errors.date)}>
            <FieldLabel htmlFor="appointment-date">{t("date")}</FieldLabel>
            <Input
              aria-invalid={Boolean(errors.date)}
              id="appointment-date"
              min={today}
              type="date"
              {...form.register("date")}
            />
            <FieldError errors={[errors.date]} />
          </Field>
          <Field data-invalid={Boolean(errors.time)}>
            <FieldLabel htmlFor="appointment-time">{t("time")}</FieldLabel>
            <Input
              aria-invalid={Boolean(errors.time)}
              id="appointment-time"
              step={300}
              type="time"
              {...form.register("time")}
            />
            <FieldError errors={[errors.time]} />
          </Field>
        </div>
        <SlotHint
          crew={crew.length ? crew.map((id) => names.get(id) ?? id) : undefined}
          day={date}
          idle={t("slotsIdle")}
          onPick={pick}
          search={search}
          slots={slots}
          time={time}
          zone={zone}
        />
      </FieldSet>
      <FieldSet>
        <FieldLegend>{t("customer")}</FieldLegend>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            className="sm:col-span-2"
            data-invalid={Boolean(errors.display_name)}
          >
            <FieldLabel htmlFor="appointment-name">
              {t("customerName")}
            </FieldLabel>
            <Input
              aria-invalid={Boolean(errors.display_name)}
              autoComplete="off"
              id="appointment-name"
              {...form.register("display_name")}
            />
            <FieldError errors={[errors.display_name]} />
          </Field>
          <Field data-invalid={Boolean(errors.email)}>
            <FieldLabel htmlFor="appointment-email">{t("email")}</FieldLabel>
            <Input
              aria-invalid={Boolean(errors.email)}
              autoComplete="off"
              id="appointment-email"
              type="email"
              {...form.register("email")}
            />
            <FieldError errors={[errors.email]} />
          </Field>
          <Field data-invalid={Boolean(errors.phone)}>
            <FieldLabel htmlFor="appointment-phone">{t("phone")}</FieldLabel>
            <Input
              aria-invalid={Boolean(errors.phone)}
              autoComplete="off"
              id="appointment-phone"
              type="tel"
              {...form.register("phone")}
            />
            <FieldError errors={[errors.phone]} />
          </Field>
        </div>
        <FieldDescription>{t("contactHint")}</FieldDescription>
        <Field data-invalid={Boolean(errors.notes)}>
          <FieldLabel htmlFor="appointment-notes">{t("notes")}</FieldLabel>
          <Textarea
            aria-invalid={Boolean(errors.notes)}
            id="appointment-notes"
            maxLength={500}
            rows={2}
            {...form.register("notes")}
          />
          <FieldDescription>{t("notesHint")}</FieldDescription>
          <FieldError errors={[errors.notes]} />
        </Field>
      </FieldSet>
      {takesMaterials ? (
        <FieldSet>
          <FieldLegend>{materials("title")}</FieldLegend>
          <FieldDescription>{materials("newDescription")}</FieldDescription>
          <MaterialsEditor
            drafts={drafts}
            idPrefix="appointment-materials"
            onChange={setEdited}
            warehouse={warehouse}
          />
        </FieldSet>
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
        <Button disabled={form.formState.isSubmitting} type="submit">
          {t("save")}
        </Button>
      </DialogFooter>
    </form>
  );
}

/** The selected appointment, with "Reschedule" and "Cancel" for managers. */
export function AppointmentDialog({
  appointment,
  canManage,
  canUseInventory = false,
  catalog,
  onChanged,
  onOpenChange,
  open,
  restoreFocus,
  teams = [],
  zone,
}: {
  appointment?: BookingAppointment;
  canManage: boolean;
  canUseInventory?: boolean;
  catalog?: BookingCatalog;
  onChanged: (appointment: BookingAppointment) => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  restoreFocus: FocusTarget;
  /** The company's teams, for „Zmień osoby”. */
  teams?: StaffTeam[];
  zone: string;
}) {
  const common = useTranslations("Common");
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto"
        closeLabel={common("close")}
        finalFocus={restoreFocus}
      >
        {appointment ? (
          <AppointmentDetails
            appointment={appointment}
            canManage={canManage}
            canUseInventory={canUseInventory}
            catalog={catalog}
            key={appointment.id}
            onChanged={onChanged}
            teams={teams}
            zone={zone}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

/** Who is on the visit, the lead named as such once there are several. */
export function crewNames(appointment: BookingAppointment, t: Translate) {
  const { crew } = appointment;
  return crew.length > 1
    ? crew
        .map((person) =>
          person.lead ? t("crewLeadName", { name: person.name }) : person.name,
        )
        .join(", ")
    : (crew[0]?.name ?? "");
}

/** „Wakat” and „Dobrano automatycznie”: only a planned visit is either. */
export function CrewBadges({
  appointment,
  short = false,
}: {
  appointment: BookingAppointment;
  /** The narrow cards: the word short, the whole of it still spoken. */
  short?: boolean;
}) {
  const t = useTranslations("Calendar");
  if (appointment.status !== "confirmed") return null;
  if (appointment.needs_assignment) {
    const missing = Math.max(
      appointment.staff_required - appointment.crew.length,
      1,
    );
    return (
      <Badge variant="destructive">
        {short ? (
          <>
            <span aria-hidden="true">{t("vacancyShort")}</span>
            <span className="sr-only">{t("vacancy", { count: missing })}</span>
          </>
        ) : (
          t("vacancy", { count: missing })
        )}
      </Badge>
    );
  }
  if (!appointment.auto_assigned) return null;
  return (
    <Badge variant="secondary">
      {short ? (
        <>
          <span aria-hidden="true">{t("autoShort")}</span>
          <span className="sr-only">{t("auto")}</span>
        </>
      ) : (
        t("auto")
      )}
    </Badge>
  );
}

function AppointmentDetails({
  appointment,
  canManage,
  canUseInventory,
  catalog,
  onChanged,
  teams,
  zone,
}: {
  appointment: BookingAppointment;
  canManage: boolean;
  canUseInventory: boolean;
  catalog?: BookingCatalog;
  onChanged: (appointment: BookingAppointment) => void;
  teams: StaffTeam[];
  zone: string;
}) {
  const t = useTranslations("Calendar");
  const locale = useLocale();
  const [notice, setNotice] = useState("");
  // The button that opened „Zmień osoby”; set while the dialog is open.
  const [changing, setChanging] = useState<HTMLElement>();
  const title = useRef<HTMLHeadingElement>(null);
  const when = formatWhen(appointment, locale, zone);
  const requested =
    appointment.requested_team?.name ??
    (appointment.requested_staff_id
      ? catalog?.staff.find(
          (item) => item.id === appointment.requested_staff_id,
        )?.name
      : undefined);
  const rows = [
    [t("service"), appointment.service_name],
    [
      appointment.crew.length > 1 ? t("crew") : t("staff"),
      crewNames(appointment, t) || t("crewNobody"),
    ],
    [t("customerChoice"), requested],
    [t("location"), appointment.location_name],
    [t("resource"), appointment.resource_name],
  ].filter((row): row is [string, string] => Boolean(row[1]));
  // A lone person has nobody to swap with — unless the visit lost them.
  const crewChangeable =
    canManage &&
    appointment.status === "confirmed" &&
    ((catalog?.staff.length ?? 0) > 1 || appointment.needs_assignment);

  return (
    <>
      <DialogHeader>
        <DialogTitle className="outline-none" ref={title} tabIndex={-1}>
          {appointment.customer_name}
        </DialogTitle>
        <DialogDescription>{when}</DialogDescription>
      </DialogHeader>
      <dl className="grid grid-cols-[auto_1fr] items-center gap-x-6 gap-y-2 text-sm">
        <dt className="text-muted-foreground">{t("statusLabel")}</dt>
        <dd className="flex flex-wrap gap-2">
          <StatusBadge status={appointment.status} />
          <CrewBadges appointment={appointment} />
        </dd>
        {rows.map(([label, value]) => (
          <Fragment key={label}>
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="font-medium">{value}</dd>
          </Fragment>
        ))}
        {appointment.customer_notes ? (
          <>
            <dt className="self-start text-muted-foreground">{t("notes")}</dt>
            <dd className="whitespace-pre-line">
              {appointment.customer_notes}
            </dd>
          </>
        ) : null}
      </dl>
      {crewChangeable ? (
        <div>
          <Button
            onClick={(event) => setChanging(event.currentTarget)}
            type="button"
            variant="outline"
          >
            {t(appointment.needs_assignment ? "assignCrew" : "changeCrew")}
          </Button>
        </div>
      ) : null}
      {changing ? (
        <CrewDialog
          appointment={appointment}
          finalFocus={changing}
          onConflict={() => onChanged(appointment)}
          onOpenChange={(open) => (open ? undefined : setChanging(undefined))}
          onSaved={(updated) => {
            setChanging(undefined);
            setNotice(t("crewSaved"));
            onChanged(updated);
          }}
          teams={teams}
          zone={zone}
        />
      ) : null}
      {appointment.takes_materials !== false &&
      (appointment.materials?.length || (canUseInventory && canManage)) ? (
        <VisitMaterials
          appointment={appointment}
          editable={
            canManage && canUseInventory && appointment.status === "confirmed"
          }
          onChanged={(updated) => {
            setNotice(t("materialsSaved"));
            onChanged(updated);
          }}
        />
      ) : null}
      <p className="text-sm text-success-foreground" role="status">
        {notice}
      </p>
      {canManage && catalog && appointment.status === "confirmed" ? (
        <DialogFooter>
          <CompleteButton
            appointment={appointment}
            onDone={(updated) => {
              setNotice(t("completed"));
              onChanged(updated);
            }}
          />
          <RescheduleDialog
            appointment={appointment}
            catalog={catalog}
            onDone={(updated) => {
              setNotice(
                t("rescheduled", { when: formatWhen(updated, locale, zone) }),
              );
              onChanged(updated);
            }}
            zone={zone}
          />
          <CancelDialog
            appointment={appointment}
            onDone={(updated) => {
              setNotice(t("canceled"));
              onChanged(updated);
            }}
            returnFocus={title}
            when={when}
          />
        </DialogFooter>
      ) : null}
    </>
  );
}

/** The visit's products; while it is confirmed they can still change. */
function VisitMaterials({
  appointment,
  editable,
  onChanged,
}: {
  appointment: BookingAppointment;
  editable: boolean;
  onChanged: (appointment: BookingAppointment) => void;
}) {
  const t = useTranslations("BookingMaterials");
  const lines = appointment.materials ?? [];
  const [drafts, setDrafts] = useState<MaterialDraft[]>();
  const warehouse = useWarehouse(drafts !== undefined);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  // What this visit already reserved counts as its own, not as a shortage.
  const held: Record<string, number> = {};
  for (const line of lines)
    held[line.item_id] = (held[line.item_id] ?? 0) + Number(line.quantity);

  async function save(next: MaterialDraft[]) {
    setBusy(true);
    setProblem("");
    try {
      onChanged(
        await setBookingAppointmentMaterials(
          appointment.id,
          materialsInput(next),
        ),
      );
      setDrafts(undefined);
    } catch (error) {
      setProblem(
        error instanceof ApiProblemError ? error.message : t("failed"),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-labelledby={`materials-${appointment.id}`}
      className="space-y-2"
    >
      <h3 className="text-sm font-medium" id={`materials-${appointment.id}`}>
        {t("title")}
      </h3>
      {drafts === undefined ? (
        <>
          <MaterialsList lines={lines} />
          {editable ? (
            <Button
              onClick={() => setDrafts(draftsOf(lines))}
              size="sm"
              type="button"
              variant="outline"
            >
              {t("edit")}
            </Button>
          ) : null}
        </>
      ) : (
        <>
          <MaterialsEditor
            drafts={drafts}
            held={held}
            idPrefix={`visit-materials-${appointment.id}`}
            onChange={setDrafts}
            warehouse={warehouse}
          />
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={busy}
              onClick={() => void save(drafts)}
              size="sm"
              type="button"
            >
              {t("save")}
            </Button>
            <Button
              onClick={() => setDrafts(undefined)}
              size="sm"
              type="button"
              variant="outline"
            >
              {t("cancelEdit")}
            </Button>
          </div>
        </>
      )}
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
    </section>
  );
}

/** The visit took place: its products leave the warehouse. */
function CompleteButton({
  appointment,
  onDone,
}: {
  appointment: BookingAppointment;
  onDone: (appointment: BookingAppointment) => void;
}) {
  const t = useTranslations("Calendar");
  // One key per visit on screen: a retry after a lost answer completes it once.
  const idempotencyKey = useRef(crypto.randomUUID());
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  async function complete() {
    setBusy(true);
    setProblem("");
    try {
      onDone(
        await completeBookingAppointment(
          appointment.id,
          idempotencyKey.current,
        ),
      );
    } catch (error) {
      setProblem(problemText(error, t, "completeError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button disabled={busy} onClick={() => void complete()} type="button">
        {t("complete")}
      </Button>
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
    </>
  );
}

function CancelDialog({
  appointment,
  onDone,
  returnFocus,
  when,
}: {
  appointment: BookingAppointment;
  onDone: (appointment: BookingAppointment) => void;
  /** The canceled visit loses this button, so focus needs another home. */
  returnFocus: RefObject<HTMLElement | null>;
  when: string;
}) {
  const t = useTranslations("Calendar");
  const common = useTranslations("Common");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [result, setResult] = useState<BookingAppointment>();
  const idempotencyKey = useRef("");

  async function confirm() {
    setBusy(true);
    setProblem(undefined);
    try {
      setResult(
        await cancelBookingAppointment(appointment.id, idempotencyKey.current),
      );
      setOpen(false);
    } catch (error) {
      setProblem(problemText(error, t, "cancelError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      onOpenChange={(next) => {
        if (next) idempotencyKey.current = crypto.randomUUID();
        setProblem(undefined);
        setOpen(next);
      }}
      // Report only once the dialog is gone: the report removes its trigger.
      onOpenChangeComplete={(isOpen) => {
        if (!isOpen && result) onDone(result);
      }}
      open={open}
    >
      <DialogTrigger render={<Button type="button" variant="destructive" />}>
        {t("cancelAppointment")}
      </DialogTrigger>
      <DialogContent
        closeLabel={common("close")}
        finalFocus={() => (result ? returnFocus.current : true)}
      >
        <DialogHeader>
          <DialogTitle>{t("cancelTitle")}</DialogTitle>
          <DialogDescription>
            {appointment.customer_name} · {when}
          </DialogDescription>
        </DialogHeader>
        <p className="text-sm">
          {t("cancelText")} {t("noCustomerMessage")}
        </p>
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
        <DialogFooter>
          <DialogClose render={<Button type="button" variant="outline" />}>
            {t("keep")}
          </DialogClose>
          <Button
            disabled={busy}
            onClick={() => void confirm()}
            type="button"
            variant="destructive"
          >
            {t("cancelConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RescheduleDialog({
  appointment,
  catalog,
  onDone,
  zone,
}: {
  appointment: BookingAppointment;
  catalog: BookingCatalog;
  onDone: (appointment: BookingAppointment) => void;
  zone: string;
}) {
  const t = useTranslations("Calendar");
  const common = useTranslations("Common");
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  return (
    <Dialog onOpenChange={setOpen} open={open}>
      <DialogTrigger render={<Button type="button" variant="outline" />}>
        {t("reschedule")}
      </DialogTrigger>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto"
        closeLabel={common("close")}
      >
        <DialogHeader>
          <DialogTitle>{t("rescheduleTitle")}</DialogTitle>
          <DialogDescription>
            {t("rescheduleCurrent", {
              customer: appointment.customer_name,
              when: formatWhen(appointment, locale, zone),
            })}
          </DialogDescription>
        </DialogHeader>
        <RescheduleForm
          appointment={appointment}
          catalog={catalog}
          onDone={(updated) => {
            setOpen(false);
            onDone(updated);
          }}
          zone={zone}
        />
      </DialogContent>
    </Dialog>
  );
}

function RescheduleForm({
  appointment,
  catalog,
  onDone,
  zone,
}: {
  appointment: BookingAppointment;
  catalog: BookingCatalog;
  onDone: (appointment: BookingAppointment) => void;
  zone: string;
}) {
  const t = useTranslations("Calendar");
  const today = wallClock(new Date(), zone).day;
  const current = wallClock(appointment.starts_at, zone);
  const [day, setDay] = useState(current.day < today ? today : current.day);
  const [time, setTime] = useState(current.time);
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const timeInput = useRef<HTMLInputElement>(null);
  // The visit's own time is taken by the visit itself: not news, not a move.
  const unchanged = day === current.day && time === current.time;
  // ponytail: an appointment carries names, not the ids a slot search needs,
  // so they are matched to the catalog by name; two services (places,
  // resources) with one name break it. Ids on Appointment would end this.
  const serviceId =
    catalog.services.find((item) => item.name === appointment.service_name)
      ?.id ?? "";
  const locationId =
    catalog.locations.find((item) => item.name === appointment.location_name)
      ?.id ?? "";
  const resourceId =
    appointment.resource_name === null
      ? null
      : catalog.resources.find(
          (item) => item.name === appointment.resource_name,
        )?.id;
  const search = useFreeSlots(serviceId, locationId, day);
  // A move keeps the people and the resource; only the time changes, and the
  // whole crew has to be free at the new one.
  const crew = appointment.crew.length
    ? appointment.crew.map((person) => person.staff_id)
    : [appointment.staff_id];
  const slots = crewSlots(search.slots, crew, crew.length, resourceId);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!day || !time) return;
    setBusy(true);
    setProblem(undefined);
    try {
      // Any time may be tried: the free-time list cannot show times that
      // overlap this visit's own slot, and the API has the last word anyway.
      onDone(
        await rescheduleBookingAppointment(
          appointment.id,
          zonedInstant(day, time, zone).toISOString(),
          idempotencyKey,
        ),
      );
    } catch (error) {
      setProblem(problemText(error, t, "rescheduleError"));
      setBusy(false);
    }
  }

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={(event) => void save(event)}
    >
      <div className="grid grid-cols-2 gap-4">
        <Field>
          <FieldLabel htmlFor="reschedule-date">{t("date")}</FieldLabel>
          <Input
            id="reschedule-date"
            min={today}
            onChange={(event) => setDay(event.target.value)}
            required
            type="date"
            value={day}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="reschedule-time">{t("time")}</FieldLabel>
          <Input
            id="reschedule-time"
            onChange={(event) => setTime(event.target.value)}
            ref={timeInput}
            required
            step={300}
            type="time"
            value={time}
          />
        </Field>
      </div>
      {serviceId && locationId ? (
        <SlotHint
          crew={
            appointment.crew.length > 1
              ? appointment.crew.map((person) => person.name)
              : undefined
          }
          day={day}
          idle=""
          onPick={(slot) => {
            const local = wallClock(slot.starts_at, zone);
            setDay(local.day);
            setTime(local.time);
            timeInput.current?.focus();
          }}
          search={search}
          slots={slots}
          time={unchanged ? "" : time}
          zone={zone}
        />
      ) : null}
      <p className="text-sm text-muted-foreground">{t("noCustomerMessage")}</p>
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      <DialogFooter>
        <DialogClose render={<Button type="button" variant="outline" />}>
          {t("back")}
        </DialogClose>
        <Button disabled={busy || !day || !time || unchanged} type="submit">
          {t("rescheduleSave")}
        </Button>
      </DialogFooter>
    </form>
  );
}
