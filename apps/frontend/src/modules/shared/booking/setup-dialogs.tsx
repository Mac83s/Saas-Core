"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import {
  createSetupGroup,
  createSetupLocation,
  createSetupResource,
  createSetupService,
  updateSetupGroup,
  updateSetupLocation,
  updateSetupResource,
  updateSetupService,
  type BookingSetup,
  type GroupSetup,
  type PlaceSetup,
  type ResourceSetup,
  type ServiceSetup,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
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
  FieldError,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Textarea } from "@saas-core/ui/components/textarea";

import {
  draftsOf,
  materialsInput,
  MaterialsEditor,
  useWarehouse,
  type MaterialDraft,
} from "./materials-editor";
import { problemText } from "./people/person-dialogs";
import {
  coordinatesOf,
  UnitContentFields,
  unitContentOf,
} from "./unit-content-fields";

/** A ready-made service of the organization's type, to start a new one from. */
export type ServiceTemplate = {
  name: string;
  durationMinutes: number;
  appointmentKind?: string | null;
};

type Choice = "none" | "team" | "person";
type TimeModel = "slot" | "range";
type RangeUnit = "night" | "day";
type ServiceValues = {
  name: string;
  timeModel: TimeModel;
  rangeUnit: RangeUnit;
  rangeStart: string;
  rangeEnd: string;
  groupIds: string[];
  duration: number;
  before: number;
  after: number;
  notice: number;
  window: number;
  staffCount: number;
  choice: Choice;
  step: number;
  online: boolean;
  confirmation: Confirmation;
  responseHours: number;
  staffIds: string[];
  locationIds: string[];
  resourceIds: string[];
};

const CHOICES: Choice[] = ["none", "team", "person"];
/** Who confirms a customer's booking (ADR-072 §8). */
const CONFIRMATIONS = ["instant", "on_request"] as const;
type Confirmation = (typeof CONFIRMATIONS)[number];
/** How often a visit may start (B6): each divides an hour. */
const SLOT_STEPS = [5, 10, 15, 20, 30, 60] as const;
type SlotStep = (typeof SLOT_STEPS)[number];
const TIME_MODELS: TimeModel[] = ["slot", "range"];
const RANGE_UNITS: RangeUnit[] = ["night", "day"];
/** Check-in and check-out, pickup and return, until the company says (ADR-072 §1). */
const RANGE_TIMES: Record<RangeUnit, [string, string]> = {
  night: ["16:00", "11:00"],
  day: ["09:00", "18:00"],
};
const clock = (value?: string | null) => (value ? value.slice(0, 5) : "");

/** Checkboxes for a set of ids; the label names each one. */
function Picks({
  idPrefix,
  items,
  onChange,
  value,
}: {
  idPrefix: string;
  items: { id: string; name: string }[];
  onChange: (next: string[]) => void;
  value: string[];
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {items.map((item) => (
        <label
          className="flex min-h-11 items-center gap-2 text-sm"
          htmlFor={`${idPrefix}-${item.id}`}
          key={item.id}
        >
          <input
            checked={value.includes(item.id)}
            className="size-4"
            id={`${idPrefix}-${item.id}`}
            onChange={(event) =>
              onChange(
                event.target.checked
                  ? [...value, item.id]
                  : value.filter((id) => id !== item.id),
              )
            }
            type="checkbox"
          />
          {item.name}
        </label>
      ))}
    </div>
  );
}

/**
 * „Dodaj usługę” / „Edytuj usługę” (board 12): what it is, how long, how many
 * people and who, where, with what, what a customer chooses on the website,
 * and — with a warehouse — the products each visit takes.
 */
export function ServiceDialog({
  canUseInventory,
  finalFocus,
  onOpenChange,
  onSaved,
  service,
  setup,
  template,
}: {
  canUseInventory: boolean;
  finalFocus: HTMLElement | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (saved: ServiceSetup, created: boolean) => void;
  /** The service being changed; none for a new one. */
  service?: ServiceSetup;
  setup: BookingSetup;
  template?: ServiceTemplate;
}) {
  const t = useTranslations("ServicesSetup");
  const common = useTranslations("Common");
  const materials = useTranslations("BookingMaterials");
  const [problem, setProblem] = useState<string>();
  const people = setup.staff;
  const places = setup.locations.filter(
    (place) => place.active || service?.location_ids.includes(place.id),
  );
  const things = setup.resources.filter(
    (thing) => thing.active || service?.resource_ids.includes(thing.id),
  );
  // A lone person or place needs no question: a new service takes it.
  const only = (items: { id: string }[]) =>
    items.length === 1 ? [items[0].id] : [];
  const schema = useMemo(() => {
    const minutes = (max: number) =>
      z
        .number({ error: t("numberRequired") })
        .int(t("numberRequired"))
        .min(0, t("minutesRange", { max }))
        .max(max, t("minutesRange", { max }));
    const visit = (values: { timeModel: TimeModel }) =>
      values.timeModel === "slot";
    return z
      .object({
        name: z.string().trim().min(1, t("nameRequired")).max(160),
        timeModel: z.enum(TIME_MODELS),
        rangeUnit: z.enum(RANGE_UNITS),
        rangeStart: z.string(),
        rangeEnd: z.string(),
        groupIds: z.array(z.string()),
        // A stay's length comes from its seasons, not from the service.
        duration: z.number().or(z.nan()),
        before: minutes(1440),
        after: minutes(1440),
        notice: minutes(129600),
        // Empty — no window of the offer's own.
        window: z
          .number()
          .int(t("bookingWindowRange"))
          .min(1, t("bookingWindowRange"))
          .max(731, t("bookingWindowRange"))
          .or(z.nan()),
        staffCount: z.number().or(z.nan()),
        choice: z.enum(CHOICES),
        step: z.number().int(),
        online: z.boolean(),
        confirmation: z.enum(CONFIRMATIONS),
        // Asked for only where the company answers each request.
        responseHours: z.number().or(z.nan()),
        staffIds: z.array(z.string()),
        locationIds: z.array(z.string()),
        resourceIds: z.array(z.string()),
      })
      .refine(
        (values) =>
          !visit(values) ||
          (Number.isInteger(values.duration) &&
            values.duration >= 5 &&
            values.duration <= 1440),
        { message: t("durationRange"), path: ["duration"] },
      )
      .refine(
        (values) =>
          values.confirmation !== "on_request" ||
          (Number.isInteger(values.responseHours) &&
            values.responseHours >= 1 &&
            values.responseHours <= 168),
        { message: t("responseHoursRange"), path: ["responseHours"] },
      )
      .refine(
        (values) =>
          !visit(values) ||
          (Number.isInteger(values.staffCount) &&
            values.staffCount >= 1 &&
            values.staffCount <= 10),
        { message: t("staffCountRange"), path: ["staffCount"] },
      )
      .refine(
        (values) =>
          !visit(values) ||
          values.choice !== "person" ||
          values.staffCount === 1,
        {
          message: t("personOnlyForOne"),
          path: ["choice"],
        },
      )
      .refine(
        (values) =>
          visit(values) ||
          values.rangeUnit !== "day" ||
          values.rangeEnd > values.rangeStart,
        { message: t("returnAfterPickup"), path: ["rangeEnd"] },
      );
  }, [t]);
  const form = useForm<ServiceValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: service?.name ?? template?.name ?? "",
      timeModel: (service?.time_model as TimeModel | undefined) ?? "slot",
      rangeUnit: (service?.range_unit as RangeUnit | undefined) || "night",
      rangeStart: clock(service?.range_start_local) || RANGE_TIMES.night[0],
      rangeEnd: clock(service?.range_end_local) || RANGE_TIMES.night[1],
      groupIds: service?.group_ids ?? [],
      duration: service?.duration_minutes ?? template?.durationMinutes ?? 30,
      before: service?.buffer_before_minutes ?? 0,
      after: service?.buffer_after_minutes ?? 0,
      notice: service?.minimum_notice_minutes ?? 60,
      window: service?.booking_window_days ?? Number.NaN,
      staffCount: service?.staff_count ?? 1,
      choice: (service?.public_staff_choice as Choice | undefined) ?? "none",
      step: service?.slot_step_minutes ?? 5,
      online: service?.online ?? true,
      confirmation:
        (service?.confirmation as Confirmation | undefined) ?? "instant",
      responseHours: service?.response_hours ?? 24,
      staffIds: service?.staff_ids ?? only(people),
      locationIds: service?.location_ids ?? only(places),
      resourceIds: service?.resource_ids ?? [],
    },
  });
  const [
    staffCount,
    staffIds,
    locationIds,
    resourceIds,
    timeModel,
    groupIds,
    confirmation,
  ] = useWatch({
    control: form.control,
    name: [
      "staffCount",
      "staffIds",
      "locationIds",
      "resourceIds",
      "timeModel",
      "groupIds",
      "confirmation",
    ],
  });
  const stay = timeModel === "range";
  const groups = (setup.groups ?? []).filter(
    (group) => group.active || service?.group_ids.includes(group.id),
  );
  const takesMaterials = canUseInventory && service?.takes_materials === true;
  const warehouse = useWarehouse(takesMaterials);
  const [drafts, setDrafts] = useState<MaterialDraft[]>();
  const errors = form.formState.errors;
  const short = staffIds.length > 0 && staffIds.length < staffCount;
  // One key for the dialog: a double click or a retry saves once (ADR-072 §11).
  const [idempotencyKey] = useState(() => crypto.randomUUID());

  const submit = form.handleSubmit(async (values) => {
    setProblem(undefined);
    const shape =
      values.timeModel === "range"
        ? {
            time_model: "range" as const,
            range_unit: values.rangeUnit,
            range_start_local: values.rangeStart || null,
            range_end_local: values.rangeEnd || null,
            booking_window_days: Number.isNaN(values.window)
              ? null
              : values.window,
            group_ids: values.groupIds,
            staff_count: 0,
            public_staff_choice: "none" as const,
            staff_ids: [],
          }
        : {
            time_model: "slot" as const,
            duration_minutes: values.duration,
            staff_count: values.staffCount,
            public_staff_choice: values.choice,
            slot_step_minutes: values.step as SlotStep,
            staff_ids: values.staffIds,
          };
    const body = {
      name: values.name.trim(),
      ...shape,
      buffer_before_minutes: values.before,
      buffer_after_minutes: values.after,
      minimum_notice_minutes: values.notice,
      online: values.online,
      // Who confirms a customer's booking: sent when it was changed.
      ...(values.confirmation !== (service?.confirmation ?? "instant") ||
      (values.confirmation === "on_request" &&
        values.responseHours !== (service?.response_hours ?? 24))
        ? {
            confirmation: values.confirmation,
            ...(values.confirmation === "on_request"
              ? { response_hours: values.responseHours }
              : {}),
          }
        : {}),
      location_ids: values.locationIds,
      resource_ids: values.resourceIds,
      ...(!service && template?.appointmentKind
        ? { appointment_kind: template.appointmentKind }
        : {}),
      ...(drafts && takesMaterials
        ? { materials: materialsInput(drafts) }
        : {}),
    };
    try {
      onSaved(
        service
          ? await updateSetupService(
              service.id,
              { ...body, expected_version: service.version },
              idempotencyKey,
            )
          : await createSetupService(body, idempotencyKey),
        !service,
      );
    } catch (error) {
      setProblem(
        problemText(error, t("failed"), t("forbidden"), {
          booking_version_conflict: t("versionConflict"),
          time_model_locked: t("timeModelLocked"),
        }),
      );
    }
  });

  const minutesField = (
    name: "duration" | "before" | "after" | "notice",
    label: string,
    hint?: string,
  ) => (
    <Field data-invalid={Boolean(errors[name])}>
      <FieldLabel htmlFor={`service-${name}`}>{label}</FieldLabel>
      <Input
        aria-invalid={Boolean(errors[name])}
        id={`service-${name}`}
        inputMode="numeric"
        min={name === "duration" ? 5 : 0}
        step={5}
        type="number"
        {...form.register(name, { valueAsNumber: true })}
      />
      {hint ? <FieldDescription>{hint}</FieldDescription> : null}
      <FieldError errors={[errors[name]]} />
    </Field>
  );

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-2xl"
        closeLabel={common("close")}
        finalFocus={() => finalFocus ?? true}
      >
        <form className="space-y-6" noValidate onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>
              {service
                ? t("editServiceTitle", { name: service.name })
                : t("newServiceTitle")}
            </DialogTitle>
            <DialogDescription>
              {t("serviceDialogDescription")}
            </DialogDescription>
          </DialogHeader>
          <FieldSet>
            <FieldLegend>{t("legendService")}</FieldLegend>
            <Field data-invalid={Boolean(errors.name)}>
              <FieldLabel htmlFor="service-name">{t("name")}</FieldLabel>
              <Input
                aria-invalid={Boolean(errors.name)}
                autoComplete="off"
                id="service-name"
                maxLength={160}
                {...form.register("name")}
              />
              <FieldError errors={[errors.name]} />
            </Field>
            <Field>
              <FieldLabel htmlFor="service-time-model">
                {t("timeModel")}
              </FieldLabel>
              <NativeSelect
                id="service-time-model"
                {...form.register("timeModel")}
              >
                {TIME_MODELS.map((model) => (
                  <option key={model} value={model}>
                    {t(`timeModel_${model}`)}
                  </option>
                ))}
              </NativeSelect>
              <FieldDescription>{t("timeModelHint")}</FieldDescription>
            </Field>
            {stay ? (
              <div className="grid gap-4 sm:grid-cols-3">
                <Field>
                  <FieldLabel htmlFor="service-range-unit">
                    {t("rangeUnit")}
                  </FieldLabel>
                  <NativeSelect
                    id="service-range-unit"
                    {...form.register("rangeUnit", {
                      onChange: (event) => {
                        const [start, end] =
                          RANGE_TIMES[event.target.value as RangeUnit];
                        form.setValue("rangeStart", start);
                        form.setValue("rangeEnd", end);
                      },
                    })}
                  >
                    {RANGE_UNITS.map((unit) => (
                      <option key={unit} value={unit}>
                        {t(`rangeUnit_${unit}`)}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
                <Field>
                  <FieldLabel htmlFor="service-range-start">
                    {t("rangeStart")}
                  </FieldLabel>
                  <Input
                    id="service-range-start"
                    type="time"
                    {...form.register("rangeStart")}
                  />
                </Field>
                <Field data-invalid={Boolean(errors.rangeEnd)}>
                  <FieldLabel htmlFor="service-range-end">
                    {t("rangeEnd")}
                  </FieldLabel>
                  <Input
                    aria-invalid={Boolean(errors.rangeEnd)}
                    id="service-range-end"
                    type="time"
                    {...form.register("rangeEnd")}
                  />
                  <FieldError errors={[errors.rangeEnd]} />
                </Field>
                <Field
                  className="sm:col-span-3"
                  data-invalid={Boolean(errors.window)}
                >
                  <FieldLabel htmlFor="service-window">
                    {t("bookingWindow")}
                  </FieldLabel>
                  <Input
                    aria-invalid={Boolean(errors.window)}
                    className="sm:max-w-40"
                    id="service-window"
                    inputMode="numeric"
                    max={731}
                    min={1}
                    type="number"
                    {...form.register("window", { valueAsNumber: true })}
                  />
                  <FieldDescription>{t("bookingWindowHint")}</FieldDescription>
                  <FieldError errors={[errors.window]} />
                </Field>
              </div>
            ) : null}
            <div className="grid gap-4 sm:grid-cols-2">
              {stay ? null : minutesField("duration", t("duration"))}
              {stay ? null : (
                <Field>
                  <FieldLabel htmlFor="service-step">
                    {t("slotStep")}
                  </FieldLabel>
                  <NativeSelect
                    id="service-step"
                    {...form.register("step", { valueAsNumber: true })}
                  >
                    {SLOT_STEPS.map((step) => (
                      <option key={step} value={step}>
                        {t("slotStepValue", { minutes: step })}
                      </option>
                    ))}
                  </NativeSelect>
                  <FieldDescription>{t("slotStepHint")}</FieldDescription>
                </Field>
              )}
              {minutesField("notice", t("notice"), t("noticeHint"))}
              {minutesField("before", t("bufferBefore"))}
              {minutesField("after", t("bufferAfter"), t("bufferHint"))}
            </div>
          </FieldSet>
          {stay ? (
            <FieldSet>
              <FieldLegend>{t("legendUnits")}</FieldLegend>
              <FieldDescription>{t("unitsHint")}</FieldDescription>
              {groups.length ? (
                <FieldSet>
                  <FieldLegend variant="label">{t("unitGroups")}</FieldLegend>
                  <Picks
                    idPrefix="service-groups"
                    items={groups}
                    onChange={(next) => form.setValue("groupIds", next)}
                    value={groupIds}
                  />
                </FieldSet>
              ) : null}
              {things.length ? (
                <FieldSet>
                  <FieldLegend variant="label">{t("singleUnits")}</FieldLegend>
                  <Picks
                    idPrefix="service-units"
                    items={things}
                    onChange={(next) => form.setValue("resourceIds", next)}
                    value={resourceIds}
                  />
                </FieldSet>
              ) : null}
              {!groupIds.length && !resourceIds.length ? (
                <p className="text-sm text-warning-foreground">
                  {t("noUnits")}
                </p>
              ) : null}
            </FieldSet>
          ) : null}
          <FieldSet className={stay ? "hidden" : undefined}>
            <FieldLegend>{t("legendWork")}</FieldLegend>
            {people.length > 1 ? (
              <Field data-invalid={Boolean(errors.staffCount)}>
                <FieldLabel htmlFor="service-staff-count">
                  {t("staffCount")}
                </FieldLabel>
                <Input
                  aria-invalid={Boolean(errors.staffCount)}
                  className="sm:max-w-32"
                  id="service-staff-count"
                  inputMode="numeric"
                  max={10}
                  min={1}
                  type="number"
                  {...form.register("staffCount", { valueAsNumber: true })}
                />
                <FieldDescription>{t("staffCountHint")}</FieldDescription>
                <FieldError errors={[errors.staffCount]} />
              </Field>
            ) : null}
            {people.length > 1 ? (
              <FieldSet>
                <FieldLegend variant="label">{t("performers")}</FieldLegend>
                <Picks
                  idPrefix="service-staff"
                  items={people}
                  onChange={(next) => form.setValue("staffIds", next)}
                  value={staffIds}
                />
                {!staffIds.length ? (
                  <p className="text-sm text-warning-foreground">
                    {t("noPerformers")}
                  </p>
                ) : short ? (
                  <p className="text-sm text-warning-foreground">
                    {t("fewerPerformers", { count: staffCount })}
                  </p>
                ) : null}
                <FieldDescription>{t("performersHint")}</FieldDescription>
              </FieldSet>
            ) : null}
            {places.length > 1 ? (
              <FieldSet>
                <FieldLegend variant="label">{t("places")}</FieldLegend>
                <Picks
                  idPrefix="service-places"
                  items={places}
                  onChange={(next) => form.setValue("locationIds", next)}
                  value={locationIds}
                />
                {!locationIds.length ? (
                  <p className="text-sm text-warning-foreground">
                    {t("noPlaces")}
                  </p>
                ) : null}
              </FieldSet>
            ) : null}
            {things.length ? (
              <FieldSet>
                <FieldLegend variant="label">{t("resources")}</FieldLegend>
                <Picks
                  idPrefix="service-resources"
                  items={things}
                  onChange={(next) => form.setValue("resourceIds", next)}
                  value={resourceIds}
                />
                <FieldDescription>{t("resourcesHint")}</FieldDescription>
              </FieldSet>
            ) : null}
          </FieldSet>
          <FieldSet className={stay ? "hidden" : undefined}>
            <FieldLegend>{t("legendPublic")}</FieldLegend>
            <FieldDescription>{t("publicHint")}</FieldDescription>
            <Field>
              <label
                className="flex min-h-11 items-center gap-2 text-sm"
                htmlFor="service-online"
              >
                <input
                  className="size-4"
                  id="service-online"
                  type="checkbox"
                  {...form.register("online")}
                />
                {t("online")}
              </label>
              <FieldDescription>{t("onlineHint")}</FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="service-confirmation">
                {t("confirmation")}
              </FieldLabel>
              <NativeSelect
                id="service-confirmation"
                {...form.register("confirmation")}
              >
                {CONFIRMATIONS.map((value) => (
                  <option key={value} value={value}>
                    {t(`confirmation_${value}`)}
                  </option>
                ))}
              </NativeSelect>
              <FieldDescription>{t("confirmationHint")}</FieldDescription>
            </Field>
            {confirmation === "on_request" ? (
              <Field data-invalid={Boolean(errors.responseHours)}>
                <FieldLabel htmlFor="service-response-hours">
                  {t("responseHours")}
                </FieldLabel>
                <Input
                  aria-invalid={Boolean(errors.responseHours)}
                  id="service-response-hours"
                  inputMode="numeric"
                  max={168}
                  min={1}
                  type="number"
                  {...form.register("responseHours", { valueAsNumber: true })}
                />
                <FieldDescription>{t("responseHoursHint")}</FieldDescription>
                <FieldError errors={[errors.responseHours]} />
              </Field>
            ) : null}
            <Field data-invalid={Boolean(errors.choice)}>
              <FieldLabel htmlFor="service-choice">{t("choice")}</FieldLabel>
              <NativeSelect
                aria-invalid={Boolean(errors.choice)}
                id="service-choice"
                {...form.register("choice")}
              >
                {CHOICES.map((choice) => (
                  <option key={choice} value={choice}>
                    {t(`choice_${choice}`)}
                  </option>
                ))}
              </NativeSelect>
              <FieldDescription>{t("choiceHint")}</FieldDescription>
              <FieldError errors={[errors.choice]} />
            </Field>
          </FieldSet>
          {takesMaterials ? (
            <FieldSet>
              <FieldLegend>{materials("title")}</FieldLegend>
              <FieldDescription>
                {materials("serviceDescription")}
              </FieldDescription>
              <MaterialsEditor
                drafts={drafts ?? draftsOf(service?.materials)}
                idPrefix="service-materials"
                onChange={setDrafts}
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
              {t("saveService")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** „Dodaj miejsce” and „Dodaj zasób”, and their edits: a name, for a place an address. */
export function ItemDialog({
  finalFocus,
  item,
  kind,
  setup,
  onOpenChange,
  onSaved,
}: {
  finalFocus: HTMLElement | null;
  item?: PlaceSetup | ResourceSetup | GroupSetup;
  kind: "location" | "resource" | "group";
  /** A unit's group and place are picked from these. */
  setup?: BookingSetup;
  onOpenChange: (open: boolean) => void;
  onSaved: (name: string, created: boolean) => void;
}) {
  const t = useTranslations("ServicesSetup");
  const common = useTranslations("Common");
  const unit =
    kind === "resource" ? (item as ResourceSetup | undefined) : undefined;
  const [name, setName] = useState(item?.name ?? "");
  const [address, setAddress] = useState(
    item && "address" in item ? item.address : "",
  );
  // On the site's booking form (B2); only a place has it.
  const [online, setOnline] = useState(
    item && "online" in item ? item.online : true,
  );
  const [groupId, setGroupId] = useState(unit?.group_id ?? "");
  const [placeId, setPlaceId] = useState(unit?.location_id ?? "");
  const [capacity, setCapacity] = useState(
    unit?.capacity ? String(unit.capacity) : "",
  );
  const [description, setDescription] = useState(
    item && "description" in item ? item.description : "",
  );
  // What guests see of a unit (ADR-072, slice 5c): asked only of a company
  // with an offer booked from–to — a chair or a room of a visit has no page.
  const stays =
    kind === "resource" &&
    Boolean(setup?.services.some((service) => service.time_model === "range"));
  const [content, setContent] = useState(() => unitContentOf(unit));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const groups = (setup?.groups ?? []).filter(
    (group) => group.active || group.id === unit?.group_id,
  );
  const places = (setup?.locations ?? []).filter(
    (place) => place.active || place.id === unit?.location_id,
  );
  const people = capacity.trim() ? Number(capacity) : null;
  const badCapacity =
    people !== null &&
    (!Number.isInteger(people) || people < 1 || people > 1000);

  async function save() {
    if (!name.trim()) {
      setProblem(t("nameRequired"));
      return;
    }
    if (badCapacity) {
      setProblem(t("capacityRange"));
      return;
    }
    const coordinates = stays ? coordinatesOf(content) : undefined;
    if (typeof coordinates === "string") {
      setProblem(
        t(
          coordinates === "incomplete"
            ? "unitCoordinatesBoth"
            : "unitCoordinatesRange",
        ),
      );
      return;
    }
    // A point nobody gave cannot be shown; said before anything is sent.
    if (coordinates && content.exact && coordinates.latitude === null) {
      setProblem(t("unitExactLocationNeedsPoint"));
      return;
    }
    setBusy(true);
    setProblem(undefined);
    try {
      if (kind === "location") {
        const body = { name: name.trim(), address: address.trim(), online };
        await (item
          ? updateSetupLocation(
              item.id,
              { ...body, expected_version: item.version },
              idempotencyKey,
            )
          : createSetupLocation(body, idempotencyKey));
      } else if (kind === "group") {
        const body = { name: name.trim(), description: description.trim() };
        await (item
          ? updateSetupGroup(
              item.id,
              { ...body, expected_version: item.version },
              idempotencyKey,
            )
          : createSetupGroup(body, idempotencyKey));
      } else {
        const body = {
          name: name.trim(),
          group_id: groupId || null,
          location_id: placeId || null,
          capacity: people,
          description: description.trim(),
          ...(coordinates
            ? {
                public: content.shown,
                public_slug: content.slug.trim(),
                city_slug: content.town,
                ...coordinates,
                show_exact_location: content.exact,
                amenities: content.amenities,
                photo_ids: content.photos,
              }
            : {}),
        };
        await (item
          ? updateSetupResource(
              item.id,
              { ...body, expected_version: item.version },
              idempotencyKey,
            )
          : createSetupResource(body, idempotencyKey));
      }
      onSaved(name.trim(), !item);
    } catch (error) {
      setProblem(
        problemText(error, t("failed"), t("forbidden"), {
          booking_version_conflict: t("versionConflict"),
          name_taken: t("groupNameTaken"),
          slug_taken: t("unitSlugTaken"),
          photo_unavailable: t("unitPhotoUnavailable"),
          city_unknown: t("unitTownUnknown"),
          coordinates_missing: t("unitExactLocationNeedsPoint"),
        }),
      );
    } finally {
      setBusy(false);
    }
  }

  const titles = {
    location: ["newPlaceTitle", "editPlaceTitle", "placeHint"],
    resource: ["newResourceTitle", "editResourceTitle", "resourceHint"],
    group: ["newGroupTitle", "editGroupTitle", "groupHint"],
  } as const;
  const [newTitle, editTitle, hint] = titles[kind];

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent
        // A unit's content makes the form long: it scrolls in place.
        className={
          stays ? "max-h-[90vh] overflow-y-auto sm:max-w-2xl" : undefined
        }
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
              {item ? t(editTitle, { name: item.name }) : t(newTitle)}
            </DialogTitle>
            <DialogDescription>{t(hint)}</DialogDescription>
          </DialogHeader>
          <Field>
            <FieldLabel htmlFor={`${kind}-name`}>{t("name")}</FieldLabel>
            <Input
              autoComplete="off"
              id={`${kind}-name`}
              maxLength={160}
              onChange={(event) => setName(event.target.value)}
              value={name}
            />
          </Field>
          {kind === "location" ? (
            <Field>
              <FieldLabel htmlFor="location-address">{t("address")}</FieldLabel>
              <Input
                autoComplete="off"
                id="location-address"
                maxLength={240}
                onChange={(event) => setAddress(event.target.value)}
                value={address}
              />
            </Field>
          ) : null}
          {kind === "location" ? (
            <Field>
              <label
                className="flex min-h-11 items-center gap-2 text-sm"
                htmlFor="location-online"
              >
                <input
                  checked={online}
                  className="size-4"
                  id="location-online"
                  onChange={(event) => setOnline(event.target.checked)}
                  type="checkbox"
                />
                {t("placeOnline")}
              </label>
              <FieldDescription>{t("placeOnlineHint")}</FieldDescription>
            </Field>
          ) : null}
          {kind === "resource" ? (
            <>
              <Field>
                <FieldLabel htmlFor="resource-group">
                  {t("groupField")}
                </FieldLabel>
                <NativeSelect
                  id="resource-group"
                  onChange={(event) => setGroupId(event.target.value)}
                  value={groupId}
                >
                  <option value="">{t("noGroup")}</option>
                  {groups.map((group) => (
                    <option key={group.id} value={group.id}>
                      {group.name}
                    </option>
                  ))}
                </NativeSelect>
                <FieldDescription>{t("groupFieldHint")}</FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor="resource-place">
                  {t("placeField")}
                </FieldLabel>
                <NativeSelect
                  id="resource-place"
                  onChange={(event) => setPlaceId(event.target.value)}
                  value={placeId}
                >
                  <option value="">{t("noPlace")}</option>
                  {places.map((place) => (
                    <option key={place.id} value={place.id}>
                      {place.name}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field data-invalid={badCapacity}>
                <FieldLabel htmlFor="resource-capacity">
                  {t("capacity")}
                </FieldLabel>
                <Input
                  aria-invalid={badCapacity}
                  id="resource-capacity"
                  inputMode="numeric"
                  max={1000}
                  min={1}
                  onChange={(event) => setCapacity(event.target.value)}
                  type="number"
                  value={capacity}
                />
                <FieldDescription>{t("capacityHint")}</FieldDescription>
              </Field>
            </>
          ) : null}
          {kind !== "location" ? (
            <Field>
              <FieldLabel htmlFor={`${kind}-description`}>
                {t("description")}
              </FieldLabel>
              <Textarea
                id={`${kind}-description`}
                maxLength={2000}
                onChange={(event) => setDescription(event.target.value)}
                rows={3}
                value={description}
              />
            </Field>
          ) : null}
          {stays && setup ? (
            <UnitContentFields
              content={content}
              onChange={setContent}
              options={setup.unit_options}
            />
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
