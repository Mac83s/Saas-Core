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
  CalendarClockIcon,
  CheckCircle2Icon,
  CircleIcon,
  ClockAlertIcon,
  HourglassIcon,
  MapPinIcon,
  MessageCircleQuestionIcon,
  NavigationIcon,
  PhoneIcon,
  UserXIcon,
  XCircleIcon,
  XIcon,
  type LucideIcon,
} from "lucide-react";

import {
  ApiProblemError,
  answerBookingRequest,
  cancelBookingAppointment,
  completeBookingAppointment,
  markBookingAppointmentNoShow,
  createBookingAppointment,
  getBookingQuote,
  getBookingSlots,
  listBookingPlaces,
  rescheduleBookingAppointment,
  setBookingAppointmentMaterials,
  setBookingAppointmentPlace,
  type BookingAppointment,
  type BookingAppointmentInput,
  type BookingCatalog,
  type BookingPlaceSuggestion,
  type BookingQuote,
  type BookingSlotList,
  type StaffTeam,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@saas-core/ui/components/combobox";
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

import { Link } from "#i18n/navigation";
import { useCompanyLocales } from "#lib/company-locales";
import { allows, type PanelAccess } from "#lib/panel-navigation";
import type {
  ProductVisitBooked,
  ProductVisitFill,
} from "#lib/product-extension";
import productCalendar from "../../../product/calendar";

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
import { MoveStayDialog } from "./occupancy/stay-dialogs";
import { changedQuote, isPriced, PanelQuote } from "./prices/panel-quote";
import {
  ExtrasPicker,
  extrasOf,
  ONE_PERSON,
  participantsOf,
  PartyFields,
  type Party,
} from "./prices/party";
import { usePriceBook } from "./prices/price-book";
import { visitName, visitPerson } from "./visit-name";

type Slot = BookingSlotList["items"][number];
type Translate = ReturnType<typeof useTranslations>;
/** Where focus goes when a dialog closes (Base UI `finalFocus`). */
type FocusTarget = () => HTMLElement | boolean | null;

/** Colour, icon and text together: status is never told by colour alone. */
const STATUS_STYLES: Record<
  string,
  { className: string; border: string; icon: LucideIcon }
> = {
  // Holds its time while it waits — for the company's answer, or for a
  // payment (ADR-072 §9).
  pending_request: {
    className: "bg-warning text-warning-foreground",
    border: "border-l-warning-foreground",
    icon: MessageCircleQuestionIcon,
  },
  pending_payment: {
    className: "bg-warning text-warning-foreground",
    border: "border-l-warning-foreground",
    icon: HourglassIcon,
  },
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
  // UX-031: not statuses, the way a confirmed visit whose time is over shows.
  passed: {
    className: "bg-secondary text-secondary-foreground",
    border: "border-l-success-foreground",
    icon: CalendarClockIcon,
  },
  unclosed: {
    className: "bg-secondary text-secondary-foreground",
    border: "border-l-warning-foreground",
    icon: ClockAlertIcon,
  },
};

export const STATUSES = Object.keys(STATUS_STYLES);

type Timed = { status: string; ends_at: string; closes_explicitly?: boolean };

/**
 * UX-031, the one rule (backend `passing.has_passed`): a confirmed visit whose
 * planned end is behind us has passed. Nobody closed it yet, so it is no longer
 * ahead and a vacancy on it is nobody's work.
 */
export function hasPassed(item: Timed, now: Date = new Date()): boolean {
  return (
    item.status === "confirmed" &&
    new Date(item.ends_at).getTime() <= now.getTime()
  );
}

/**
 * What a visit is shown as: its status, or for a passed one `passed` („took
 * place, to settle”) — `unclosed` when its module closes it itself, so the
 * time being over does not mean the work was done.
 */
export function shownStatus(item: Timed, now?: Date): string {
  if (!hasPassed(item, now)) return item.status;
  return item.closes_explicitly ? "unclosed" : "passed";
}

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

/**
 * Where the visit takes place — its town, when the module that owns the visit
 * knows it (a farm's village). Nothing when no module says.
 */
export function VisitPlace({
  place,
  className,
}: {
  place: string | null | undefined;
  className?: string;
}) {
  const t = useTranslations("Calendar");
  if (!place) return null;
  return (
    <span className={cn("flex min-w-0 items-center gap-1", className)}>
      <MapPinIcon aria-hidden="true" className="size-3.5 shrink-0" />
      <span className="sr-only">{t("town")}: </span>
      {/* A product may say why the visit is elsewhere („Wizyta domowa”). */}
      <span className="truncate">{t("placeAway", { place })}</span>
    </span>
  );
}

/** The company's places a module keeps (its farms, say), once per form. */
function useSavedPlaces(enabled: boolean) {
  const [places, setPlaces] = useState<BookingPlaceSuggestion[]>([]);
  useEffect(() => {
    if (!enabled) return;
    let current = true;
    // The places help; the form works without them.
    listBookingPlaces()
      .then((items) => {
        if (current) setPlaces(items);
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, [enabled]);
  return places;
}

/** More saved places than this get a search instead of a list. */
const FILTERABLE_PLACES = 12;

/** Picks one of the company's places; choosing fills the town and address. */
function SavedPlacePicker({
  id,
  onPick,
  places,
}: {
  id: string;
  onPick: (place: BookingPlaceSuggestion) => void;
  places: BookingPlaceSuggestion[];
}) {
  const t = useTranslations("Calendar");
  const label = (place: BookingPlaceSuggestion) =>
    [place.name, place.town].filter(Boolean).join(" · ");
  if (places.length > FILTERABLE_PLACES)
    return (
      <Combobox
        items={places}
        itemToStringLabel={label}
        onValueChange={(place: BookingPlaceSuggestion | null) => {
          if (place) onPick(place);
        }}
        value={null}
      >
        <ComboboxInput id={id} placeholder={t("placeSavedSearch")} />
        <ComboboxContent>
          <ComboboxEmpty>{t("placeSavedNone")}</ComboboxEmpty>
          <ComboboxList>
            {places.map((place, index) => (
              <ComboboxItem key={index} value={place}>
                {label(place)}
              </ComboboxItem>
            ))}
          </ComboboxList>
        </ComboboxContent>
      </Combobox>
    );
  return (
    <NativeSelect
      id={id}
      onChange={(event) => {
        const place = places[Number(event.target.value)];
        if (event.target.value && place) onPick(place);
      }}
      value=""
    >
      <option value="">{t("placeSavedChoose")}</option>
      {places.map((place, index) => (
        <option key={index} value={index}>
          {label(place)}
        </option>
      ))}
    </NativeSelect>
  );
}

/** „Miejsce wizyty” as one line: the town, then the street. */
function placeLine(appointment: BookingAppointment) {
  return [
    appointment.place_town || appointment.place,
    appointment.place_address,
  ]
    .filter(Boolean)
    .join(", ");
}

/** A product's marks on a visit (ADR-067), worded by its messages. */
export function FlagBadges({ flags }: { flags?: string[] }) {
  const t = useTranslations("Calendar");
  if (!flags?.length) return null;
  return (
    <>
      {flags.map((flag) => (
        <Badge key={flag} variant="outline">
          {t.has(`flags.${flag}`) ? t(`flags.${flag}`) : flag}
        </Badge>
      ))}
    </>
  );
}

/** The product's section for a kind of visit, when this person may use it. */
function productSection(access: PanelAccess | undefined, kind?: string) {
  return productCalendar &&
    access &&
    kind &&
    productCalendar.kinds.includes(kind) &&
    allows(access, productCalendar)
    ? productCalendar
    : null;
}

/** The product whose part stands under a visit's details, for the kinds it extends. */
function productDetails(access: PanelAccess | undefined, kind = "") {
  if (!productCalendar || !access || !allows(access, productCalendar))
    return null;
  const kinds = productCalendar.detailsKinds ?? productCalendar.kinds;
  return kinds.includes(kind) ? productCalendar : null;
}

/** Google Maps for the place's town and street: the person's own app opens it. */
function mapLink(line: string) {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(line)}`;
}

/** The form's own fields a server's validation answer names (one place to
 * change when the API's field errors change shape). */
const SERVER_FIELDS: Record<string, keyof NewValues> = {
  "customer.display_name": "display_name",
  "customer.email": "email",
  "customer.phone": "phone",
  customer_notes: "notes",
  place_town: "place_town",
  place_address: "place_address",
};

function fieldProblems(error: unknown): [keyof NewValues, string][] {
  if (!(error instanceof ApiProblemError)) return [];
  const detail = error.problem.detail;
  if (!detail || typeof detail !== "object") return [];
  const found: [keyof NewValues, string][] = [];
  const walk = (value: unknown, path: string) => {
    if (Array.isArray(value) && typeof value[0] === "string") {
      const field = SERVER_FIELDS[path];
      if (field) found.push([field, value[0]]);
    } else if (value && typeof value === "object")
      for (const [key, inner] of Object.entries(value))
        walk(inner, path ? `${path}.${key}` : key);
  };
  walk(detail, "");
  return found;
}

function problemText(error: unknown, t: Translate, fallback: string) {
  switch (error instanceof ApiProblemError ? error.problem.code : "") {
    case "slot_unavailable":
      return t("slotTaken");
    case "booking_idempotency_conflict":
      return t("idempotencyConflict");
    case "appointment_not_changeable":
      return t("notChangeable");
    case "visit_not_started_yet":
      return t("noShowTooEarly");
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
  place_town: string;
  place_address: string;
};

export function NewAppointmentDialog({
  access,
  canUseInventory = false,
  catalog,
  day,
  params = {},
  serviceId = "",
  staffId = "",
  time = "",
  onCreated,
  onOpenChange,
  open,
  restoreFocus,
  teams = [],
  zone,
}: {
  /** What a product's section may offer this person (ADR-067). */
  access?: PanelAccess;
  canUseInventory?: boolean;
  catalog: BookingCatalog;
  /** The day the calendar shows; the form starts there unless it is past. */
  day: string;
  /** A product's parameters from the calendar's address, for its section. */
  params?: Readonly<Record<string, string>>;
  /** The service a link names (`service_id`). */
  serviceId?: string;
  /** The person the calendar is filtered to: the form starts with them. */
  staffId?: string;
  /** "HH:mm" of a free window picked on the day board (plan: phase 4). */
  time?: string;
  /** Whom and when: a product's section books its own kind itself. */
  onCreated: (appointment: ProductVisitBooked) => void;
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
          access={access}
          canUseInventory={canUseInventory}
          catalog={catalog}
          day={day}
          params={params}
          serviceId={serviceId}
          onCreated={onCreated}
          staffId={staffId}
          teams={teams}
          time={time}
          zone={zone}
        />
      </DialogContent>
    </Dialog>
  );
}

function NewAppointmentForm({
  access,
  canUseInventory,
  catalog,
  day,
  onCreated,
  params,
  serviceId: linkedService,
  staffId: chosenStaff,
  teams,
  time: chosenTime,
  zone,
}: {
  access?: PanelAccess;
  canUseInventory: boolean;
  catalog: BookingCatalog;
  day: string;
  params: Readonly<Record<string, string>>;
  serviceId: string;
  /** Whom and when: a product's section books its own kind itself. */
  onCreated: (appointment: ProductVisitBooked) => void;
  staffId: string;
  teams: StaffTeam[];
  time: string;
  zone: string;
}) {
  const t = useTranslations("Calendar");
  const common = useTranslations("Common");
  const today = wallClock(new Date(), zone).day;
  // The customer's language is one of the company's, its first unless picked;
  // never the panel's (ADR-071 pkt 21). Empty: the server takes the first.
  const customerLocales = useCompanyLocales([]);
  const [customerLocale, setCustomerLocale] = useState("");
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
  const prices = useTranslations("PriceList");
  const pricing = usePriceBook();
  const [party, setParty] = useState<Party>(ONE_PERSON);
  const [picked, setPicked] = useState<Record<string, number>>({});
  const [priced, setPriced] = useState<{
    key: string;
    quote?: BookingQuote;
    refused?: string;
    /** Another price than the form showed when it was sent (409). */
    changed?: boolean;
  }>();
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
          place_town: z.string().trim().max(120, t("placeTooLong")),
          place_address: z.string().trim().max(240, t("placeTooLong")),
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
      service_id: catalog.services.some((item) => item.id === linkedService)
        ? linkedService
        : only(catalog.services),
      location_id: only(catalog.locations),
      date: day < today ? today : day,
      time: day < today ? "" : chosenTime,
      display_name: "",
      email: "",
      phone: "",
      notes: "",
      place_town: "",
      place_address: "",
    },
  });
  const savedPlaces = useSavedPlaces(Boolean(catalog.place_search));
  // A product's section for its own kind of visit (ADR-067): it may fill the
  // customer and the place, and it books the visit itself.
  const [sectionValue, setSectionValue] = useState<unknown>();
  const [sectionErrors, setSectionErrors] = useState<Record<string, string>>(
    {},
  );
  const [serviceId, locationId, date, time] = useWatch({
    control: form.control,
    name: ["service_id", "location_id", "date", "time"],
  });
  // „Zmień dla tej wizyty” opens the fields for the section's value it was
  // pressed at; another farm is summed up again (answer 50a).
  const [openedFor, setOpenedFor] = useState<unknown>();
  const [customerName, customerPhone, customerEmail, placeTown, placeAddress] =
    useWatch({
      control: form.control,
      name: ["display_name", "phone", "email", "place_town", "place_address"],
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
  const section = productSection(access, chosen?.appointment_kind);
  const Section = section?.formSection;
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
  // The price of what is chosen now (ADR-072 §7): the server's quote for the
  // service, the time, the people and the extras. The price list only says
  // what to ask about; no price shown never stops a booking.
  const startsAt = time
    ? findSlot(slots, date, time, zone)?.starts_at
    : undefined;
  const offerExtras = (pricing.book?.extras ?? []).filter(
    (extra) =>
      extra.service_id === serviceId && extra.active && extra.kind === "charge",
  );
  const peopleMatter =
    (pricing.book?.prices ?? []).some(
      (rule) =>
        rule.service_id === serviceId &&
        rule.active &&
        (rule.basis === "per_person" ||
          rule.included_people !== null ||
          rule.category_prices.length > 0),
    ) || offerExtras.some((extra) => extra.basis === "per_person");
  const options = offerExtras.filter((extra) => !extra.mandatory);
  const participants = peopleMatter ? participantsOf(party) : undefined;
  const extras = extrasOf(
    Object.fromEntries(
      options.map((extra) => [extra.id, picked[extra.id] ?? 0]),
    ),
  );
  const quoteKey =
    serviceId && startsAt
      ? JSON.stringify([
          serviceId,
          startsAt,
          participants,
          extras,
          customerLocale,
        ])
      : "";
  const quote = priced?.key === quoteKey ? priced : undefined;
  useEffect(() => {
    if (!quoteKey || !startsAt) return;
    let live = true;
    getBookingQuote({
      service_id: serviceId,
      starts_at: startsAt,
      ...(participants ? { participants } : {}),
      ...(extras.length ? { extras } : {}),
      ...(customerLocale ? { locale: customerLocale } : {}),
    })
      .then((found) => {
        if (live) setPriced({ key: quoteKey, quote: found });
      })
      .catch((error: unknown) => {
        // What the price list refuses, in its own words; the booking would
        // be refused the same.
        const refused =
          error instanceof ApiProblemError && error.problem.status === 400
            ? error.problem.errors?.[0]?.message
            : undefined;
        if (live) setPriced({ key: quoteKey, refused });
      });
    return () => {
      live = false;
    };
    // The key says everything that is asked.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quoteKey]);
  const errors = form.formState.errors;
  // A refused field is never hidden behind the summary.
  const summed =
    Boolean(section?.summarizes?.(sectionValue)) &&
    openedFor !== sectionValue &&
    !(
      errors.display_name ||
      errors.email ||
      errors.phone ||
      errors.place_town ||
      errors.place_address
    );

  function pick(slot: Slot) {
    const local = wallClock(slot.starts_at, zone);
    form.setValue("date", local.day);
    form.setValue("time", local.time);
    form.clearErrors("time");
    form.setFocus("time");
  }

  // A field the section names is written, "" included: choosing another farm
  // names them all, so the first one's street or phone does not stay. A field
  // it leaves out stays as the person typed it (a card typed key by key).
  function fill(values: ProductVisitFill) {
    const groups: [
      Record<string, string | undefined> | undefined,
      [string, keyof NewValues][],
    ][] = [
      [
        values.customer,
        [
          ["display_name", "display_name"],
          ["phone", "phone"],
          ["email", "email"],
        ],
      ],
      [
        values.place,
        [
          ["town", "place_town"],
          ["address", "place_address"],
        ],
      ],
    ];
    for (const [group, fields] of groups)
      for (const [key, field] of fields)
        if (group && key in group)
          form.setValue(field, group[key] ?? "", { shouldDirty: true });
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
    const town = values.place_town.trim();
    const address = values.place_address.trim();
    const input: BookingAppointmentInput = {
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
        ...(customerLocale ? { locale: customerLocale } : {}),
      },
      ...(notes ? { customer_notes: notes } : {}),
      ...(town || address ? { place_town: town, place_address: address } : {}),
      ...(edited && takesMaterials
        ? { materials: materialsInput(edited) }
        : {}),
      ...(participants ? { participants } : {}),
      ...(extras.length ? { extras } : {}),
      // The price shown: another one by now is asked about, not booked.
      ...(isPriced(quote?.quote) ? { quote_digest: quote?.quote?.digest } : {}),
    };
    const checked = section?.check(sectionValue, input) ?? {};
    setSectionErrors(checked);
    if (Object.keys(checked).length) {
      setProblem(t("sectionInvalid"));
      return;
    }
    try {
      onCreated(
        section
          ? await section.save({ input, value: sectionValue, idempotencyKey })
          : await createBookingAppointment(input, idempotencyKey),
      );
    } catch (error) {
      // „Cena się zmieniła”: the new amounts, and the next save books at them.
      const fresh = changedQuote(error);
      if (fresh) {
        setPriced({ key: quoteKey, quote: fresh, changed: true });
        return;
      }
      if (
        error instanceof ApiProblemError &&
        error.problem.code === "slot_unavailable"
      )
        setVersion((value) => value + 1);
      const own = section?.problemErrors?.(error);
      if (own) setSectionErrors(own);
      for (const [field, message] of fieldProblems(error))
        form.setError(field, { message });
      setProblem(problemText(error, t, "createError"));
    }
  }

  return (
    <form className="space-y-6" noValidate onSubmit={form.handleSubmit(submit)}>
      <FieldSet>
        {/* With one place there is no place to choose (UX plan W4). */}
        <FieldLegend>
          {t(catalog.locations.length > 1 ? "serviceAndPlace" : "service")}
        </FieldLegend>
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
            // Nobody named: one sentence says what happens (UX plan W4).
            <p className="text-sm">{t("crewAutoHint")}</p>
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
          {crew.length ? (
            <FieldDescription>{t("crewAutoHint")}</FieldDescription>
          ) : null}
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
      {Section && chosen && access ? (
        <Section
          access={access}
          errors={sectionErrors}
          fill={fill}
          onChange={setSectionValue}
          params={params}
          service={chosen}
          value={sectionValue}
        />
      ) : null}
      {peopleMatter ||
      options.length ||
      isPriced(quote?.quote) ||
      quote?.refused ? (
        <FieldSet>
          <FieldLegend>{prices("quoteTitle")}</FieldLegend>
          {peopleMatter ? (
            <FieldSet>
              <FieldLegend variant="label">{prices("partyLegend")}</FieldLegend>
              <PartyFields
                categories={(pricing.book?.categories ?? []).filter(
                  (category) => category.active,
                )}
                idPrefix="appointment-party"
                onChange={setParty}
                value={party}
              />
            </FieldSet>
          ) : null}
          {options.length ? (
            <FieldSet>
              <FieldLegend variant="label">
                {prices("extrasLegend")}
              </FieldLegend>
              <ExtrasPicker
                extras={options}
                idPrefix="appointment-extra"
                onChange={setPicked}
                value={picked}
              />
            </FieldSet>
          ) : null}
          {quote?.quote && isPriced(quote.quote) ? (
            <PanelQuote changed={quote.changed} quote={quote.quote} />
          ) : null}
          {quote?.refused ? (
            <p className="text-sm text-destructive" role="alert">
              {quote.refused}
            </p>
          ) : null}
        </FieldSet>
      ) : null}
      <FieldSet>
        <FieldLegend>{t("customer")}</FieldLegend>
        {summed ? (
          <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 rounded-lg border bg-muted/40 p-3 text-sm">
            <div className="min-w-0 space-y-0.5 wrap-anywhere">
              <p className="font-medium">{customerName}</p>
              <p className="text-muted-foreground">
                {[customerPhone, customerEmail].filter(Boolean).join(" · ")}
              </p>
              <p className="text-muted-foreground">
                {[placeTown, placeAddress].filter(Boolean).join(", ")}
              </p>
            </div>
            <Button
              className="h-auto p-0"
              onClick={() => setOpenedFor(sectionValue)}
              type="button"
              variant="link"
            >
              {t("changeForVisit")}
            </Button>
          </div>
        ) : null}
        <div
          className={cn("grid gap-4 sm:grid-cols-2", summed && "hidden")}
          data-slot="customer-fields"
        >
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
          {customerLocales.length > 1 && (
            <Field>
              <FieldLabel htmlFor="appointment-customer-locale">
                {t("customerLocale")}
              </FieldLabel>
              <NativeSelect
                id="appointment-customer-locale"
                onChange={(event) => setCustomerLocale(event.target.value)}
                value={customerLocale || customerLocales[0]?.code}
              >
                {customerLocales.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.name}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          )}
        </div>
        {summed ? null : (
          <FieldDescription>{t("contactHint")}</FieldDescription>
        )}
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
      <FieldSet className={cn(summed && "hidden")}>
        <FieldLegend>{t("placeLegend")}</FieldLegend>
        <FieldDescription>{t("placeHint")}</FieldDescription>
        {/* A product's section owns the places of its own visits. */}
        {savedPlaces.length && !section ? (
          <Field>
            <FieldLabel htmlFor="appointment-saved-place">
              {t("placeSaved")}
            </FieldLabel>
            <SavedPlacePicker
              id="appointment-saved-place"
              onPick={(place) => {
                form.setValue("place_town", place.town);
                form.setValue("place_address", place.address);
              }}
              places={savedPlaces}
            />
            <FieldDescription>{t("placeSavedHint")}</FieldDescription>
          </Field>
        ) : null}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field data-invalid={Boolean(errors.place_town)}>
            <FieldLabel htmlFor="appointment-town">{t("town")}</FieldLabel>
            <Input
              aria-invalid={Boolean(errors.place_town)}
              autoComplete="off"
              id="appointment-town"
              maxLength={120}
              {...form.register("place_town")}
            />
            <FieldError errors={[errors.place_town]} />
          </Field>
          <Field data-invalid={Boolean(errors.place_address)}>
            <FieldLabel htmlFor="appointment-address">
              {t("placeAddress")}
            </FieldLabel>
            <Input
              aria-invalid={Boolean(errors.place_address)}
              autoComplete="off"
              id="appointment-address"
              maxLength={240}
              {...form.register("place_address")}
            />
            <FieldError errors={[errors.place_address]} />
          </Field>
        </div>
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
  access,
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
  /** What a product's section under the details may offer (ADR-067). */
  access?: PanelAccess;
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
            access={access}
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

/**
 * „Wakat” and „Dobrano automatycznie”: only a visit still ahead is either — on
 * one that has passed, nobody is to be found any more (UX-031).
 */
export function CrewBadges({
  appointment,
  short = false,
}: {
  appointment: BookingAppointment;
  /** The narrow cards: the word short, the whole of it still spoken. */
  short?: boolean;
}) {
  const t = useTranslations("Calendar");
  if (appointment.status !== "confirmed" || hasPassed(appointment)) return null;
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
  access,
  appointment,
  canManage,
  canUseInventory,
  catalog,
  onChanged,
  teams,
  zone,
}: {
  access?: PanelAccess;
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
    // The person behind a visit that goes by its farm's name (UX plan W2).
    [t("customer"), visitPerson(appointment)],
    [
      appointment.crew.length > 1 ? t("crew") : t("staff"),
      crewNames(appointment, t) || t("crewNobody"),
    ],
    [t("customerChoice"), requested],
    [t("location"), appointment.location_name],
    [t("resource"), appointment.resource_name],
  ].filter((row): row is [string, string] => Boolean(row[1]));
  const Details = productDetails(
    access,
    appointment.appointment_kind,
  )?.detailsSection;
  // A lone person has nobody to swap with — unless the visit lost them.
  const crewChangeable =
    canManage &&
    appointment.status === "confirmed" &&
    ((catalog?.staff.length ?? 0) > 1 || appointment.needs_assignment);

  return (
    <>
      <DialogHeader>
        <DialogTitle className="outline-none" ref={title} tabIndex={-1}>
          {visitName(appointment)}
        </DialogTitle>
        <DialogDescription>{when}</DialogDescription>
      </DialogHeader>
      <dl className="grid grid-cols-[auto_1fr] items-center gap-x-6 gap-y-2 text-sm">
        <dt className="text-muted-foreground">{t("statusLabel")}</dt>
        <dd className="flex flex-wrap gap-2">
          <StatusBadge status={shownStatus(appointment)} />
          <CrewBadges appointment={appointment} />
          <FlagBadges flags={appointment.flags} />
        </dd>
        {/* A booking that waits says until when (ADR-072 §9). */}
        {(appointment.status === "pending_payment" ||
          appointment.status === "pending_request") &&
        appointment.hold_expires_at ? (
          <>
            <dt className="text-muted-foreground">
              {t(
                appointment.status === "pending_request"
                  ? "answerUntil"
                  : "holdUntil",
              )}
            </dt>
            <dd className="font-medium">
              {dateFormat(locale, {
                day: "numeric",
                month: "long",
                hour: "2-digit",
                minute: "2-digit",
                timeZone: zone,
              }).format(new Date(appointment.hold_expires_at))}
            </dd>
          </>
        ) : null}
        {/* Only for whoever may read orders: the API names none otherwise. */}
        {appointment.order ? (
          <>
            <dt className="text-muted-foreground">{t("order")}</dt>
            <dd>
              <Link
                className="font-medium text-primary hover:underline"
                href={`/panel/orders/${appointment.order.id}`}
              >
                {appointment.order.number}
              </Link>
            </dd>
          </>
        ) : null}
        {rows.map(([label, value]) => (
          <Fragment key={label}>
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="font-medium">{value}</dd>
          </Fragment>
        ))}
        {/* Only whoever plans and the people on the visit get them (ADR-067). */}
        {appointment.customer_phone ? (
          <>
            <dt className="text-muted-foreground">{t("phone")}</dt>
            <dd>
              <a
                className="inline-flex min-h-8 items-center gap-1.5 font-medium text-primary hover:underline"
                href={`tel:${appointment.customer_phone.replace(/[^\d+]/g, "")}`}
              >
                <PhoneIcon aria-hidden="true" className="size-4" />
                {appointment.customer_phone}
              </a>
            </dd>
          </>
        ) : null}
        {appointment.customer_email ? (
          <>
            <dt className="text-muted-foreground">{t("email")}</dt>
            <dd>
              <a
                className="font-medium break-all text-primary hover:underline"
                href={`mailto:${encodeURIComponent(appointment.customer_email)}`}
              >
                {appointment.customer_email}
              </a>
            </dd>
          </>
        ) : null}
        {appointment.customer_notes ? (
          <>
            <dt className="self-start text-muted-foreground">{t("notes")}</dt>
            <dd className="whitespace-pre-line">
              {appointment.customer_notes}
            </dd>
          </>
        ) : null}
      </dl>
      {/* What the booking costs, as it was frozen when it was made (§7). */}
      {appointment.quote && isPriced(appointment.quote) ? (
        <PanelQuote quote={appointment.quote} />
      ) : null}
      <VisitPlaceSection
        appointment={appointment}
        catalog={catalog}
        editable={canManage && appointment.status !== "canceled"}
        onChanged={(updated) => {
          setNotice(t("placeSavedNotice"));
          onChanged(updated);
        }}
      />
      {Details && access ? (
        <Details
          access={access}
          appointment={appointment}
          onChanged={onChanged}
        />
      ) : null}
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
          {/* Before the start nobody can tell (UX-031). */}
          {new Date(appointment.starts_at) <= new Date() ? (
            <NoShowDialog
              appointment={appointment}
              onDone={(updated) => {
                setNotice(t("noShowDone"));
                onChanged(updated);
              }}
              returnFocus={title}
              when={when}
            />
          ) : null}
          {/* A stay moves by its dates, not by a slot (ADR-072 phase 2d). */}
          {appointment.time_model === "range" ? (
            <MoveStayDialog
              appointment={appointment}
              onDone={(updated) => {
                setNotice(
                  t("rescheduled", { when: formatWhen(updated, locale, zone) }),
                );
                onChanged(updated);
              }}
              zone={zone}
            />
          ) : (
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
          )}
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
      {/* A customer's request waits for the company's answer (ADR-072 §9). */}
      {appointment.status === "pending_request" ? (
        <>
          <p className="text-sm text-muted-foreground">{t("requestHint")}</p>
          {canManage ? (
            <AnswerRequest
              appointment={appointment}
              onDone={(updated) => {
                setNotice(
                  t(
                    updated.status === "canceled"
                      ? "requestDeclined"
                      : updated.status === "pending_payment"
                        ? "requestAcceptedAwaiting"
                        : "requestAccepted",
                  ),
                );
                onChanged(updated);
              }}
              returnFocus={title}
              when={when}
            />
          ) : null}
        </>
      ) : null}
      {/* A booking that waits for its payment is confirmed in its order —
          the payment is marked there — or called off; it is never moved. */}
      {appointment.status === "pending_payment" ? (
        <>
          <p className="text-sm text-muted-foreground">
            {t(appointment.order ? "pendingHint" : "pendingHintNoOrder")}
          </p>
          {canManage ? (
            <DialogFooter>
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
      ) : null}
    </>
  );
}

/** „Miejsce wizyty” (ADR-066), changed in place like the products. */
function VisitPlaceSection({
  appointment,
  catalog,
  editable,
  onChanged,
}: {
  appointment: BookingAppointment;
  catalog?: BookingCatalog;
  editable: boolean;
  onChanged: (appointment: BookingAppointment) => void;
}) {
  const t = useTranslations("Calendar");
  const common = useTranslations("Common");
  const [draft, setDraft] = useState<{ town: string; address: string }>();
  const places = useSavedPlaces(
    draft !== undefined && Boolean(catalog?.place_search),
  );
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const heading = `place-${appointment.id}`;
  const line = placeLine(appointment);
  if (!editable && !line) return null;

  async function save(next: { town: string; address: string }) {
    setBusy(true);
    setProblem("");
    try {
      onChanged(
        await setBookingAppointmentPlace(appointment.id, {
          town: next.town.trim(),
          address: next.address.trim(),
        }),
      );
      setDraft(undefined);
    } catch (error) {
      setProblem(problemText(error, t, "placeError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby={heading} className="space-y-2">
      <h3 className="text-sm font-medium" id={heading}>
        {t("placeLegend")}
      </h3>
      {draft === undefined ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className={cn("text-sm", !line && "text-muted-foreground")}>
            {line ? (
              <VisitPlace className="text-sm" place={line} />
            ) : (
              t("placeNone")
            )}
          </p>
          {line ? (
            <a
              className={buttonVariants({ size: "sm", variant: "outline" })}
              href={mapLink(line)}
              rel="noopener noreferrer"
              target="_blank"
            >
              <NavigationIcon aria-hidden="true" />
              {t("navigate")}
              <span className="sr-only">{t("opensNewTab")}</span>
            </a>
          ) : null}
          {editable ? (
            <Button
              onClick={() =>
                setDraft({
                  town: appointment.place_town ?? "",
                  address: appointment.place_address ?? "",
                })
              }
              size="sm"
              type="button"
              variant="outline"
            >
              {t("placeChange")}
            </Button>
          ) : null}
        </div>
      ) : (
        <form
          className="space-y-3"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void save(draft);
          }}
        >
          {places.length ? (
            <Field>
              <FieldLabel htmlFor={`${heading}-saved`}>
                {t("placeSaved")}
              </FieldLabel>
              <SavedPlacePicker
                id={`${heading}-saved`}
                onPick={(place) =>
                  setDraft({ town: place.town, address: place.address })
                }
                places={places}
              />
            </Field>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor={`${heading}-town`}>{t("town")}</FieldLabel>
              <Input
                autoComplete="off"
                id={`${heading}-town`}
                maxLength={120}
                onChange={(event) =>
                  setDraft({ ...draft, town: event.target.value })
                }
                value={draft.town}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor={`${heading}-address`}>
                {t("placeAddress")}
              </FieldLabel>
              <Input
                autoComplete="off"
                id={`${heading}-address`}
                maxLength={240}
                onChange={(event) =>
                  setDraft({ ...draft, address: event.target.value })
                }
                value={draft.address}
              />
            </Field>
          </div>
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button disabled={busy} size="sm" type="submit">
              {common("save")}
            </Button>
            <Button
              onClick={() => setDraft(undefined)}
              size="sm"
              type="button"
              variant="outline"
            >
              {common("cancel")}
            </Button>
          </div>
        </form>
      )}
    </section>
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

/**
 * The customer did not come (UX-031): the visit closes without having taken
 * place. Asked first, because there is no undo.
 */
function NoShowDialog({
  appointment,
  onDone,
  returnFocus,
  when,
}: {
  appointment: BookingAppointment;
  onDone: (appointment: BookingAppointment) => void;
  /** The closed visit loses this button, so focus needs another home. */
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
        await markBookingAppointmentNoShow(
          appointment.id,
          idempotencyKey.current,
        ),
      );
      setOpen(false);
    } catch (error) {
      setProblem(problemText(error, t, "noShowError"));
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
      <DialogTrigger render={<Button type="button" variant="outline" />}>
        {t("noShow")}
      </DialogTrigger>
      <DialogContent
        closeLabel={common("close")}
        finalFocus={() => (result ? returnFocus.current : true)}
      >
        <DialogHeader>
          <DialogTitle>{t("noShowTitle")}</DialogTitle>
          <DialogDescription>
            {visitName(appointment)} · {when}
          </DialogDescription>
        </DialogHeader>
        <p className="text-sm">{t("noShowText")}</p>
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
        <DialogFooter>
          <DialogClose render={<Button type="button" variant="outline" />}>
            {t("keep")}
          </DialogClose>
          <Button disabled={busy} onClick={() => void confirm()} type="button">
            {t("noShowConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** „Przyjmij” and „Odmów” for a booking made on request: accepting acts at
 *  once, declining asks first — the customer is told either way. */
function AnswerRequest({
  appointment,
  onDone,
  returnFocus,
  when,
}: {
  appointment: BookingAppointment;
  onDone: (appointment: BookingAppointment) => void;
  /** The answered request loses these buttons, so focus needs another home. */
  returnFocus: RefObject<HTMLElement | null>;
  when: string;
}) {
  const t = useTranslations("Calendar");
  const common = useTranslations("Common");
  const [declining, setDeclining] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [declined, setDeclined] = useState<BookingAppointment>();
  // One key per answer: a double click or a retry answers once.
  const keys = useRef<{ accept?: string; decline?: string }>({});

  async function answer(kind: "accept" | "decline") {
    setBusy(true);
    setProblem(undefined);
    keys.current[kind] ??= crypto.randomUUID();
    try {
      const updated = await answerBookingRequest(
        appointment.id,
        kind,
        keys.current[kind],
      );
      if (kind === "accept") {
        returnFocus.current?.focus();
        onDone(updated);
      } else {
        setDeclined(updated);
        setDeclining(false);
      }
    } catch (error) {
      setProblem(problemText(error, t, "answerError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {problem && !declining ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      <DialogFooter>
        <Button
          disabled={busy}
          onClick={() => void answer("accept")}
          type="button"
        >
          {t("acceptRequest")}
        </Button>
        <Dialog
          onOpenChange={(next) => {
            setProblem(undefined);
            setDeclining(next);
          }}
          // Report only once the dialog is gone: the report removes its trigger.
          onOpenChangeComplete={(isOpen) => {
            if (!isOpen && declined) onDone(declined);
          }}
          open={declining}
        >
          <DialogTrigger
            render={<Button type="button" variant="destructive" />}
          >
            {t("declineRequest")}
          </DialogTrigger>
          <DialogContent
            closeLabel={common("close")}
            finalFocus={() => (declined ? returnFocus.current : true)}
          >
            <DialogHeader>
              <DialogTitle>{t("declineTitle")}</DialogTitle>
              <DialogDescription>
                {visitName(appointment)} · {when}
              </DialogDescription>
            </DialogHeader>
            <p className="text-sm">{t("declineText")}</p>
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
                onClick={() => void answer("decline")}
                type="button"
                variant="destructive"
              >
                {t("declineConfirm")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </DialogFooter>
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
            {visitName(appointment)} · {when}
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
              customer: visitName(appointment),
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
    : appointment.staff_id
      ? [appointment.staff_id]
      : [];
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
