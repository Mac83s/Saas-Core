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

/** A ready-made service of the organization's type, to start a new one from. */
export type ServiceTemplate = {
  name: string;
  durationMinutes: number;
  appointmentKind?: string | null;
};

type Choice = "none" | "team" | "person";
type ServiceValues = {
  name: string;
  duration: number;
  before: number;
  after: number;
  notice: number;
  staffCount: number;
  choice: Choice;
  staffIds: string[];
  locationIds: string[];
  resourceIds: string[];
};

const CHOICES: Choice[] = ["none", "team", "person"];

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
    return z
      .object({
        name: z.string().trim().min(1, t("nameRequired")).max(160),
        duration: z
          .number({ error: t("numberRequired") })
          .int(t("numberRequired"))
          .min(5, t("durationRange"))
          .max(1440, t("durationRange")),
        before: minutes(1440),
        after: minutes(1440),
        notice: minutes(129600),
        staffCount: z
          .number({ error: t("numberRequired") })
          .int(t("numberRequired"))
          .min(1, t("staffCountRange"))
          .max(10, t("staffCountRange")),
        choice: z.enum(CHOICES),
        staffIds: z.array(z.string()),
        locationIds: z.array(z.string()),
        resourceIds: z.array(z.string()),
      })
      .refine(
        (values) => values.choice !== "person" || values.staffCount === 1,
        {
          message: t("personOnlyForOne"),
          path: ["choice"],
        },
      );
  }, [t]);
  const form = useForm<ServiceValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: service?.name ?? template?.name ?? "",
      duration: service?.duration_minutes ?? template?.durationMinutes ?? 30,
      before: service?.buffer_before_minutes ?? 0,
      after: service?.buffer_after_minutes ?? 0,
      notice: service?.minimum_notice_minutes ?? 60,
      staffCount: service?.staff_count ?? 1,
      choice: (service?.public_staff_choice as Choice | undefined) ?? "none",
      staffIds: service?.staff_ids ?? only(people),
      locationIds: service?.location_ids ?? only(places),
      resourceIds: service?.resource_ids ?? [],
    },
  });
  const [staffCount, staffIds, locationIds, resourceIds] = useWatch({
    control: form.control,
    name: ["staffCount", "staffIds", "locationIds", "resourceIds"],
  });
  const takesMaterials = canUseInventory && service?.takes_materials === true;
  const warehouse = useWarehouse(takesMaterials);
  const [drafts, setDrafts] = useState<MaterialDraft[]>();
  const errors = form.formState.errors;
  const short = staffIds.length > 0 && staffIds.length < staffCount;
  // One key for the dialog: a double click or a retry saves once (ADR-072 §11).
  const [idempotencyKey] = useState(() => crypto.randomUUID());

  const submit = form.handleSubmit(async (values) => {
    setProblem(undefined);
    const body = {
      name: values.name.trim(),
      duration_minutes: values.duration,
      buffer_before_minutes: values.before,
      buffer_after_minutes: values.after,
      minimum_notice_minutes: values.notice,
      staff_count: values.staffCount,
      public_staff_choice: values.choice,
      staff_ids: values.staffIds,
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
            <div className="grid gap-4 sm:grid-cols-2">
              {minutesField("duration", t("duration"))}
              {minutesField("notice", t("notice"), t("noticeHint"))}
              {minutesField("before", t("bufferBefore"))}
              {minutesField("after", t("bufferAfter"), t("bufferHint"))}
            </div>
          </FieldSet>
          <FieldSet>
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
          <FieldSet>
            <FieldLegend>{t("legendPublic")}</FieldLegend>
            <FieldDescription>{t("publicHint")}</FieldDescription>
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
  const [groupId, setGroupId] = useState(unit?.group_id ?? "");
  const [placeId, setPlaceId] = useState(unit?.location_id ?? "");
  const [capacity, setCapacity] = useState(
    unit?.capacity ? String(unit.capacity) : "",
  );
  const [description, setDescription] = useState(
    item && "description" in item ? item.description : "",
  );
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
    setBusy(true);
    setProblem(undefined);
    try {
      if (kind === "location") {
        const body = { name: name.trim(), address: address.trim() };
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
