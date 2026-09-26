"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import {
  addPerson,
  createInvitation,
  type BookingCatalog,
  type Person,
  type RoleCatalog,
  type SeatUsage,
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
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Switch } from "@saas-core/ui/components/switch";
import { cn } from "@saas-core/ui/lib/utils";

import {
  assignableRoles,
  managesTeam,
} from "../../../core/organizations/role-groups";
import { useRoleLabel } from "../../../core/organizations/role-labels";
import { problemText, RoleSelect, useRoleHint } from "./person-dialogs";

type Values = {
  name: string;
  phone: string;
  access: "invite" | "none";
  email: string;
  role: string;
  takesVisits: boolean;
  serviceIds: string[];
  weekdays: number[];
  from: string;
  to: string;
  locationId: string;
  copyFrom: string;
};

const WEEK = [0, 1, 2, 3, 4, 5, 6];

/**
 * "Dodaj pracownika" (plan, board 2): a person with an account or without one,
 * and — when they take visits — what they do and when, in one step. Where the
 * company has no calendar it is an invitation to the panel, nothing more.
 */
export function AddPersonDialog({
  open,
  onOpenChange,
  booking,
  canBook,
  canInvite,
  canManageMembers,
  roles,
  organizationType,
  seats,
  onAdded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The calendar's services, places and people; null without booking. */
  booking: { catalog: BookingCatalog; people: Person[] } | null;
  /** booking.appointment.manage: add people and their hours. */
  canBook: boolean;
  /** Full or limited member management: send invitations. */
  canInvite: boolean;
  /** organization.members.manage: every role, not only the limited ones. */
  canManageMembers: boolean;
  roles: RoleCatalog;
  organizationType?: string;
  seats: SeatUsage | null;
  onAdded: (added: { name: string; email?: string }) => void;
}) {
  const t = useTranslations("People");
  const common = useTranslations("Common");
  const roleLabel = useRoleLabel(roles, organizationType);
  const hint = useRoleHint(roles);
  const [problem, setProblem] = useState<string>();
  const calendar = canBook ? booking : null;
  const groups = assignableRoles(roles.roles, canManageMembers);
  const firstRole = groups.work[0]?.key ?? groups.management[0]?.key ?? "";
  const locations = calendar?.catalog.locations ?? [];
  const services = calendar?.catalog.services ?? [];
  // A person the office set by hand keeps that choice when the role changes.
  const [visitsTouched, setVisitsTouched] = useState(false);

  const schema = useMemo(
    () =>
      z
        .object({
          name: z.string().trim().max(160),
          phone: z.string().trim().max(40),
          access: z.enum(["invite", "none"]),
          email: z.string().trim(),
          role: z.string(),
          takesVisits: z.boolean(),
          serviceIds: z.array(z.string()),
          weekdays: z.array(z.number()),
          from: z.string(),
          to: z.string(),
          locationId: z.string(),
          copyFrom: z.string(),
        })
        .superRefine((values, context) => {
          const issue = (path: keyof Values, message: string) =>
            context.addIssue({ code: "custom", path: [path], message });
          if (calendar && !values.name) issue("name", t("required"));
          if (values.access === "invite") {
            if (!z.email().safeParse(values.email).success)
              issue("email", t("invalidEmail"));
            if (!values.role) issue("role", t("required"));
          }
          if (!calendar || !values.takesVisits) return;
          if (!values.serviceIds.length)
            issue("serviceIds", t("chooseServices"));
          if (values.copyFrom) return;
          if (!values.weekdays.length) issue("weekdays", t("chooseDays"));
          if (values.to <= values.from) issue("to", t("hoursOrder"));
          if (locations.length > 1 && !values.locationId)
            issue("locationId", t("required"));
        }),
    [calendar, locations.length, t],
  );
  const defaults: Values = {
    name: "",
    phone: "",
    access: canInvite ? "invite" : "none",
    email: "",
    role: firstRole,
    takesVisits: Boolean(calendar && services.length),
    serviceIds: services.length === 1 ? [services[0].id] : [],
    weekdays: [0, 1, 2, 3, 4],
    from: "08:00",
    to: "16:00",
    locationId: locations.length === 1 ? locations[0].id : "",
    copyFrom: "",
  };
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: defaults,
  });
  const [access, role, takesVisits, weekdays, serviceIds, copyFrom] = useWatch({
    control: form.control,
    name: [
      "access",
      "role",
      "takesVisits",
      "weekdays",
      "serviceIds",
      "copyFrom",
    ],
  });
  const errors = form.formState.errors;
  const full =
    access === "invite" &&
    seats?.limit !== null &&
    seats !== null &&
    seats.used >= seats.limit;
  const management = roles.roles.filter(managesTeam);
  const withHours = (calendar?.people ?? []).filter(
    (person) => person.active && person.has_hours,
  );

  function openChange(next: boolean) {
    if (next) {
      form.reset(defaults);
      setVisitsTouched(false);
      setProblem(undefined);
    }
    onOpenChange(next);
  }

  // "On for working roles and people without an account, off for management"
  // (board 2) — until the office decides otherwise.
  function suggestVisits(nextAccess: string, nextRole: string) {
    if (visitsTouched || !calendar || !services.length) return;
    const managing = roles.roles.find((item) => item.key === nextRole);
    form.setValue(
      "takesVisits",
      nextAccess === "none" || !managing || !managesTeam(managing),
    );
  }

  const submit = form.handleSubmit(async (values) => {
    setProblem(undefined);
    const invitation =
      values.access === "invite"
        ? { email: values.email.trim(), role: values.role }
        : null;
    try {
      if (calendar) {
        const visits = values.takesVisits;
        await addPerson({
          name: values.name.trim(),
          phone: values.phone.trim(),
          invitation,
          service_ids: visits ? values.serviceIds : [],
          hours:
            visits && !values.copyFrom
              ? {
                  weekdays: values.weekdays,
                  local_start: values.from,
                  local_end: values.to,
                  location_id: values.locationId || null,
                }
              : null,
          copy_hours_from: visits && values.copyFrom ? values.copyFrom : null,
        });
      } else if (invitation) {
        await createInvitation(invitation);
      }
      onOpenChange(false);
      onAdded({ name: values.name.trim(), email: invitation?.email });
    } catch (error) {
      setProblem(
        problemText(error, t("failed"), t("forbidden"), {
          invitation_conflict: t("inviteConflict"),
        }),
      );
    }
  });

  const dayButton = (day: number) => {
    const on = weekdays.includes(day);
    return (
      <Button
        aria-label={t(`dayLong_${day}`)}
        aria-pressed={on}
        key={day}
        onClick={() =>
          form.setValue(
            "weekdays",
            on
              ? weekdays.filter((item) => item !== day)
              : [...weekdays, day].sort(),
            { shouldValidate: form.formState.isSubmitted },
          )
        }
        size="sm"
        type="button"
        variant={on ? "default" : "outline"}
      >
        {t(`day_${day}`)}
      </Button>
    );
  };

  return (
    <Dialog onOpenChange={openChange} open={open}>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-2xl"
        closeLabel={common("close")}
      >
        <form className="space-y-5" onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>{t("addTitle")}</DialogTitle>
            <DialogDescription>
              {calendar ? t("addDescription") : t("addDescriptionAccounts")}
            </DialogDescription>
          </DialogHeader>

          {calendar ? (
            <FieldSet>
              <FieldLegend>{t("legendPerson")}</FieldLegend>
              <FieldGroup className="grid gap-4 sm:grid-cols-2">
                <Field data-invalid={Boolean(errors.name)}>
                  <FieldLabel htmlFor="add-person-name">{t("name")}</FieldLabel>
                  <Input
                    aria-invalid={Boolean(errors.name)}
                    autoComplete="off"
                    id="add-person-name"
                    {...form.register("name")}
                  />
                  <FieldError errors={[errors.name]} />
                </Field>
                <Field>
                  <FieldLabel htmlFor="add-person-phone">
                    {t("phone")}
                  </FieldLabel>
                  <Input
                    aria-describedby="add-person-phone-hint"
                    autoComplete="off"
                    id="add-person-phone"
                    type="tel"
                    {...form.register("phone")}
                  />
                  <FieldDescription id="add-person-phone-hint">
                    {t("phoneHint")}
                  </FieldDescription>
                </Field>
              </FieldGroup>
            </FieldSet>
          ) : null}

          <FieldSet>
            <FieldLegend>{t("legendAccess")}</FieldLegend>
            {canInvite && calendar ? (
              <div className="grid gap-2 sm:grid-cols-2">
                {(["invite", "none"] as const).map((value) => (
                  <label
                    className="flex cursor-pointer items-start gap-3 rounded-lg border p-3 has-checked:border-primary has-checked:bg-primary/5"
                    key={value}
                  >
                    <input
                      className="mt-1 size-4 accent-primary"
                      type="radio"
                      value={value}
                      {...form.register("access", {
                        onChange: (event) =>
                          suggestVisits(event.target.value, role),
                      })}
                    />
                    <span>
                      <span className="block font-medium">
                        {t(value === "invite" ? "byEmail" : "noAccount")}
                      </span>
                      <span className="block text-sm text-muted-foreground">
                        {t(
                          value === "invite" ? "byEmailHint" : "noAccountHint",
                        )}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            ) : null}
            {access === "invite" ? (
              <FieldGroup className="grid gap-4 sm:grid-cols-2">
                <Field data-invalid={Boolean(errors.email)}>
                  <FieldLabel htmlFor="add-person-email">
                    {t("email")}
                  </FieldLabel>
                  <Input
                    aria-invalid={Boolean(errors.email)}
                    autoComplete="off"
                    id="add-person-email"
                    type="email"
                    {...form.register("email")}
                  />
                  <FieldError errors={[errors.email]} />
                </Field>
                <Field data-invalid={Boolean(errors.role)}>
                  <FieldLabel htmlFor="add-person-role">{t("role")}</FieldLabel>
                  <RoleSelect
                    canManage={canManageMembers}
                    catalog={roles}
                    describedBy="add-person-role-hint"
                    id="add-person-role"
                    organizationType={organizationType}
                    {...form.register("role", {
                      onChange: (event) =>
                        suggestVisits(access, event.target.value),
                    })}
                  />
                  <FieldDescription id="add-person-role-hint">
                    {hint(role)}
                  </FieldDescription>
                </Field>
                {management.length ? (
                  <p className="text-sm text-muted-foreground sm:col-span-2">
                    {t("managementNote", {
                      roles: management
                        .filter((item) => item.key !== "owner")
                        .map((item) => roleLabel(item.key))
                        .join(", "),
                    })}
                  </p>
                ) : null}
              </FieldGroup>
            ) : null}
          </FieldSet>

          {calendar ? (
            <FieldSet>
              <FieldLegend>{t("legendVisits")}</FieldLegend>
              {services.length && locations.length ? (
                <>
                  <Field>
                    <label className="flex min-h-11 items-center gap-3 font-medium">
                      <Switch
                        aria-describedby="add-person-visits-hint"
                        checked={takesVisits}
                        onCheckedChange={(checked) => {
                          setVisitsTouched(true);
                          form.setValue("takesVisits", checked);
                        }}
                      />
                      {t("takesVisits")}
                    </label>
                    <p
                      className="text-sm text-muted-foreground"
                      id="add-person-visits-hint"
                    >
                      {t("takesVisitsHint")}
                    </p>
                  </Field>
                  {takesVisits ? (
                    <FieldGroup>
                      <FieldSet data-invalid={Boolean(errors.serviceIds)}>
                        <FieldLegend variant="label">
                          {t("services")}
                        </FieldLegend>
                        <div className="grid gap-2 sm:grid-cols-2">
                          {services.map((service) => (
                            <label
                              className="flex items-center gap-2 text-sm"
                              key={service.id}
                            >
                              <input
                                checked={serviceIds.includes(service.id)}
                                className="size-4"
                                onChange={(event) =>
                                  form.setValue(
                                    "serviceIds",
                                    event.target.checked
                                      ? [...serviceIds, service.id]
                                      : serviceIds.filter(
                                          (id) => id !== service.id,
                                        ),
                                    {
                                      shouldValidate:
                                        form.formState.isSubmitted,
                                    },
                                  )
                                }
                                type="checkbox"
                              />
                              {service.name}
                            </label>
                          ))}
                        </div>
                        <FieldError errors={[errors.serviceIds]} />
                      </FieldSet>
                      {withHours.length ? (
                        <Field>
                          <FieldLabel htmlFor="add-person-copy">
                            {t("copyFrom")}
                          </FieldLabel>
                          <NativeSelect
                            id="add-person-copy"
                            {...form.register("copyFrom")}
                          >
                            <option value="">{t("copyNone")}</option>
                            {withHours.map((person) => (
                              <option key={person.id} value={person.id}>
                                {person.name}
                              </option>
                            ))}
                          </NativeSelect>
                        </Field>
                      ) : null}
                      {copyFrom ? null : (
                        <>
                          <FieldSet data-invalid={Boolean(errors.weekdays)}>
                            <FieldLegend variant="label">
                              {t("workDays")}
                            </FieldLegend>
                            <div className="flex flex-wrap gap-1.5">
                              {WEEK.map(dayButton)}
                            </div>
                            <FieldError errors={[errors.weekdays]} />
                          </FieldSet>
                          <div
                            className={cn(
                              "grid gap-4",
                              locations.length > 1
                                ? "sm:grid-cols-3"
                                : "sm:grid-cols-2",
                            )}
                          >
                            <Field>
                              <FieldLabel htmlFor="add-person-from">
                                {t("from")}
                              </FieldLabel>
                              <Input
                                id="add-person-from"
                                type="time"
                                {...form.register("from")}
                              />
                            </Field>
                            <Field data-invalid={Boolean(errors.to)}>
                              <FieldLabel htmlFor="add-person-to">
                                {t("to")}
                              </FieldLabel>
                              <Input
                                aria-invalid={Boolean(errors.to)}
                                id="add-person-to"
                                type="time"
                                {...form.register("to")}
                              />
                              <FieldError errors={[errors.to]} />
                            </Field>
                            {locations.length > 1 ? (
                              <Field data-invalid={Boolean(errors.locationId)}>
                                <FieldLabel htmlFor="add-person-place">
                                  {t("place")}
                                </FieldLabel>
                                <NativeSelect
                                  id="add-person-place"
                                  {...form.register("locationId")}
                                >
                                  <option value="">{t("choose")}</option>
                                  {locations.map((location) => (
                                    <option
                                      key={location.id}
                                      value={location.id}
                                    >
                                      {location.name}
                                    </option>
                                  ))}
                                </NativeSelect>
                                <FieldError errors={[errors.locationId]} />
                              </Field>
                            ) : null}
                          </div>
                        </>
                      )}
                    </FieldGroup>
                  ) : null}
                </>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t("visitsSetupFirst")}
                </p>
              )}
            </FieldSet>
          ) : null}

          {access === "invite" && seats?.limit != null ? (
            <p
              className={cn(
                "text-sm",
                full ? "text-destructive" : "text-muted-foreground",
              )}
            >
              {full
                ? t("seatsFull", { limit: seats.limit })
                : t("seatsAfter", { used: seats.used + 1, limit: seats.limit })}
            </p>
          ) : null}
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button
              disabled={form.formState.isSubmitting || Boolean(full)}
              type="submit"
            >
              {access === "invite" ? t("submitInvite") : t("submitAdd")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
