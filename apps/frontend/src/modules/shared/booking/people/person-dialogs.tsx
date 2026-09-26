"use client";

import { useMemo, useState, type ComponentProps, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  addPerson,
  addTimeOff,
  invitePerson,
  setPersonServices,
  updatePerson,
  type BookingCatalog,
  type MembershipSummary,
  type RoleCatalog,
  type TimeOffCreated,
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

import { assignableRoles } from "../../../core/organizations/role-groups";
import {
  useRoleDescription,
  useRoleLabel,
} from "../../../core/organizations/role-labels";
import { addDays, zonedInstant } from "../calendar-time";

/**
 * The server's own words when it has them, a generic line otherwise; `codes`
 * gives a stable problem code a sentence of the screen's own.
 */
export function problemText(
  error: unknown,
  fallback: string,
  forbidden: string,
  codes: Record<string, string> = {},
): string {
  if (!(error instanceof ApiProblemError)) return fallback;
  const known = error.problem.code ? codes[error.problem.code] : undefined;
  if (known) return known;
  if (error.problem.status === 403) return forbidden;
  return typeof error.problem.detail === "string" && error.problem.detail
    ? error.problem.detail
    : fallback;
}

function Problem({ text }: { text?: string }) {
  return text ? (
    <p className="text-sm text-destructive" role="alert">
      {text}
    </p>
  ) : null;
}

type Focus = HTMLElement | null | undefined;

/** A yes-or-no question before an action that is hard to undo. */
export function ConfirmDialog({
  open,
  title,
  description,
  confirm,
  destructive = false,
  extra,
  onConfirm,
  onOpenChange,
  finalFocus,
}: {
  open: boolean;
  title: string;
  description: ReactNode;
  confirm: string;
  destructive?: boolean;
  /** Under the description: a warning, a way out. */
  extra?: ReactNode;
  /** Returns the problem to show, or nothing when it worked. */
  onConfirm: () => Promise<string | undefined>;
  onOpenChange: (open: boolean) => void;
  finalFocus?: Focus;
}) {
  const common = useTranslations("Common");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next) setProblem(undefined);
        onOpenChange(next);
      }}
      open={open}
    >
      <DialogContent
        closeLabel={common("close")}
        finalFocus={() => finalFocus ?? true}
      >
        <form
          className="space-y-4"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setProblem(await onConfirm());
            setBusy(false);
          }}
        >
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          {extra}
          <Problem text={problem} />
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button
              disabled={busy}
              type="submit"
              variant={destructive ? "destructive" : "default"}
            >
              {confirm}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** A role picker with the management roles first (plan: phase 2). */
export function RoleSelect({
  id,
  catalog,
  canManage,
  organizationType,
  value,
  describedBy,
  ...props
}: {
  id: string;
  catalog: RoleCatalog;
  canManage: boolean;
  organizationType?: string;
  value?: string;
  describedBy?: string;
} & Omit<ComponentProps<"select">, "id" | "value">) {
  const t = useTranslations("People");
  const roleLabel = useRoleLabel(catalog, organizationType);
  const groups = assignableRoles(catalog.roles, canManage);
  return (
    <NativeSelect
      aria-describedby={describedBy}
      id={id}
      value={value}
      {...props}
    >
      {groups.management.length ? (
        <optgroup label={t("groupManagement")}>
          {groups.management.map((role) => (
            <option key={role.key} value={role.key}>
              {roleLabel(role.key)}
            </option>
          ))}
        </optgroup>
      ) : null}
      {groups.work.length ? (
        <optgroup label={t("groupWork")}>
          {groups.work.map((role) => (
            <option key={role.key} value={role.key}>
              {roleLabel(role.key)}
            </option>
          ))}
        </optgroup>
      ) : null}
    </NativeSelect>
  );
}

/** What a role opens, under its picker, from the role's permissions. */
export function useRoleHint(catalog: RoleCatalog | undefined) {
  const describe = useRoleDescription(catalog);
  return (key: string) => {
    const role = catalog?.roles.find((item) => item.key === key);
    return role ? describe(role) : "";
  };
}

/**
 * Name, phone and the services a person does. A person edits their own phone
 * only; an account without a calendar entry gets one when first saved.
 */
export function EditPersonDialog({
  open,
  onOpenChange,
  person,
  catalog,
  canManage,
  onSaved,
  finalFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  person: {
    staffId?: string;
    membershipId?: string;
    name: string;
    phone: string;
    serviceIds: string[];
  };
  catalog?: BookingCatalog;
  /** booking.appointment.manage: name and services too, not only the phone. */
  canManage: boolean;
  onSaved: (name: string) => void;
  finalFocus?: Focus;
}) {
  const t = useTranslations("People");
  const common = useTranslations("Common");
  const [name, setName] = useState(person.name);
  const [phone, setPhone] = useState(person.phone);
  const [services, setServices] = useState(new Set(person.serviceIds));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  async function save() {
    setBusy(true);
    setProblem(undefined);
    try {
      const trimmed = name.trim();
      if (!person.staffId)
        await addPerson({
          name: trimmed,
          phone: phone.trim(),
          membership_id: person.membershipId,
          service_ids: [...services],
        });
      else {
        await updatePerson(
          person.staffId,
          canManage
            ? { name: trimmed, phone: phone.trim() }
            : { phone: phone.trim() },
        );
        const before = new Set(person.serviceIds);
        if (
          canManage &&
          (before.size !== services.size ||
            [...services].some((id) => !before.has(id)))
        )
          await setPersonServices(person.staffId, [...services]);
      }
      onSaved(trimmed);
    } catch (error) {
      setProblem(problemText(error, t("failed"), t("forbidden")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent
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
            <DialogTitle>{t("editTitle", { name: person.name })}</DialogTitle>
            <DialogDescription>{t("editDescription")}</DialogDescription>
          </DialogHeader>
          <FieldGroup>
            {canManage ? (
              <Field>
                <FieldLabel htmlFor="person-name">{t("name")}</FieldLabel>
                <Input
                  id="person-name"
                  maxLength={160}
                  onChange={(event) => setName(event.target.value)}
                  required
                  value={name}
                />
              </Field>
            ) : null}
            <Field>
              <FieldLabel htmlFor="person-phone">{t("phone")}</FieldLabel>
              <Input
                aria-describedby="person-phone-hint"
                autoComplete="tel"
                id="person-phone"
                maxLength={40}
                onChange={(event) => setPhone(event.target.value)}
                type="tel"
                value={phone}
              />
              <FieldDescription id="person-phone-hint">
                {t("phoneHint")}
              </FieldDescription>
            </Field>
            {canManage && catalog?.services.length ? (
              <FieldSet>
                <FieldLegend>{t("services")}</FieldLegend>
                <div className="grid gap-2 sm:grid-cols-2">
                  {catalog.services.map((service) => (
                    <label
                      className="flex items-center gap-2 text-sm"
                      key={service.id}
                    >
                      <input
                        checked={services.has(service.id)}
                        className="size-4"
                        onChange={(event) => {
                          const next = new Set(services);
                          if (event.target.checked) next.add(service.id);
                          else next.delete(service.id);
                          setServices(next);
                        }}
                        type="checkbox"
                      />
                      {service.name}
                    </label>
                  ))}
                </div>
              </FieldSet>
            ) : null}
          </FieldGroup>
          <Problem text={problem} />
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button
              disabled={busy || (canManage && !name.trim())}
              type="submit"
            >
              {t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Whole days away, in the organization's zone; the reason is seen by
 * management and the person only (an illness is health data, ADR-058 §9).
 */
export function TimeOffDialog({
  open,
  onOpenChange,
  staffId,
  name,
  today,
  zone,
  onAdded,
  finalFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  staffId: string;
  name: string;
  /** The organization's today, "YYYY-MM-DD". */
  today: string;
  zone: string;
  onAdded: (result: TimeOffCreated) => void;
  finalFocus?: Focus;
}) {
  const t = useTranslations("People");
  const common = useTranslations("Common");
  const schema = useMemo(
    () =>
      z
        .object({
          from: z.string().min(1, t("required")),
          to: z.string().min(1, t("required")),
          reason: z.string().trim().max(160),
        })
        .refine((values) => values.to >= values.from, {
          message: t("timeOffOrder"),
          path: ["to"],
        }),
    [t],
  );
  const form = useForm<{ from: string; to: string; reason: string }>({
    resolver: zodResolver(schema),
    defaultValues: { from: today, to: today, reason: "" },
  });
  const [problem, setProblem] = useState<string>();

  const submit = form.handleSubmit(async (values) => {
    setProblem(undefined);
    try {
      onAdded(
        await addTimeOff(staffId, {
          starts_at: zonedInstant(values.from, "00:00", zone).toISOString(),
          ends_at: zonedInstant(
            addDays(values.to, 1),
            "00:00",
            zone,
          ).toISOString(),
          reason: values.reason,
        }),
      );
      form.reset({ from: today, to: today, reason: "" });
    } catch (error) {
      setProblem(problemText(error, t("failed"), t("forbidden")));
    }
  });

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent
        closeLabel={common("close")}
        finalFocus={() => finalFocus ?? true}
      >
        <form className="space-y-4" onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>{t("timeOffTitle", { name })}</DialogTitle>
            <DialogDescription>{t("timeOffDescription")}</DialogDescription>
          </DialogHeader>
          <FieldGroup className="grid gap-4 sm:grid-cols-2">
            <Field data-invalid={Boolean(form.formState.errors.from)}>
              <FieldLabel htmlFor="time-off-from">
                {t("timeOffFrom")}
              </FieldLabel>
              <Input
                id="time-off-from"
                type="date"
                {...form.register("from")}
              />
              <FieldError errors={[form.formState.errors.from]} />
            </Field>
            <Field data-invalid={Boolean(form.formState.errors.to)}>
              <FieldLabel htmlFor="time-off-to">{t("timeOffTo")}</FieldLabel>
              <Input id="time-off-to" type="date" {...form.register("to")} />
              <FieldError errors={[form.formState.errors.to]} />
            </Field>
            <Field className="sm:col-span-2">
              <FieldLabel htmlFor="time-off-reason">
                {t("timeOffReason")}
              </FieldLabel>
              <Input
                id="time-off-reason"
                maxLength={160}
                {...form.register("reason")}
              />
            </Field>
          </FieldGroup>
          <Problem text={problem} />
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button disabled={form.formState.isSubmitting} type="submit">
              {t("timeOffSubmit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** An account for someone added without one; accepting links it to them. */
export function InviteDialog({
  open,
  onOpenChange,
  staffId,
  name,
  email = "",
  role,
  catalog,
  canManage,
  organizationType,
  onInvited,
  finalFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  staffId: string;
  name: string;
  email?: string;
  role?: string;
  catalog: RoleCatalog;
  canManage: boolean;
  organizationType?: string;
  onInvited: (email: string) => void;
  finalFocus?: Focus;
}) {
  const t = useTranslations("People");
  const common = useTranslations("Common");
  const hint = useRoleHint(catalog);
  const groups = assignableRoles(catalog.roles, canManage);
  const [address, setAddress] = useState(email);
  const [chosen, setChosen] = useState(
    role ?? groups.work[0]?.key ?? groups.management[0]?.key ?? "",
  );
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent
        closeLabel={common("close")}
        finalFocus={() => finalFocus ?? true}
      >
        <form
          className="space-y-4"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setProblem(undefined);
            try {
              await invitePerson(staffId, {
                email: address.trim(),
                role: chosen,
              });
              onInvited(address.trim());
            } catch (error) {
              setProblem(
                problemText(error, t("failed"), t("forbidden"), {
                  invitation_conflict: t("inviteConflict"),
                }),
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          <DialogHeader>
            <DialogTitle>{t("inviteTitle", { name })}</DialogTitle>
            <DialogDescription>{t("inviteDescription")}</DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="invite-person-email">
                {t("email")}
              </FieldLabel>
              <Input
                autoComplete="off"
                id="invite-person-email"
                onChange={(event) => setAddress(event.target.value)}
                required
                type="email"
                value={address}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="invite-person-role">{t("role")}</FieldLabel>
              <RoleSelect
                canManage={canManage}
                catalog={catalog}
                describedBy="invite-person-role-hint"
                id="invite-person-role"
                onChange={(event) => setChosen(event.target.value)}
                organizationType={organizationType}
                value={chosen}
              />
              <FieldDescription id="invite-person-role-hint">
                {hint(chosen)}
              </FieldDescription>
            </Field>
          </FieldGroup>
          <Problem text={problem} />
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button disabled={busy || !address.trim() || !chosen} type="submit">
              {t("inviteSubmit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The account a person without one already has on the team: two records of
 * one human, made before the team screen joined them (the old link card).
 */
export function LinkAccountDialog({
  open,
  onOpenChange,
  staffId,
  name,
  members,
  onLinked,
  finalFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  staffId: string;
  name: string;
  /** Active accounts without a calendar entry of their own. */
  members: MembershipSummary[];
  onLinked: (member: MembershipSummary) => void;
  finalFocus?: Focus;
}) {
  const t = useTranslations("People");
  const [chosen, setChosen] = useState(members[0]?.id ?? "");
  const [problem, setProblem] = useState<string>();
  const label = (member: MembershipSummary) => {
    const full = [member.first_name, member.last_name].join(" ").trim();
    return full ? `${full} (${member.email})` : member.email;
  };
  return (
    <ConfirmDialog
      confirm={t("linkSubmit")}
      description={t("linkDescription")}
      extra={
        <Field>
          <FieldLabel htmlFor="link-account">{t("linkAccount")}</FieldLabel>
          <NativeSelect
            id="link-account"
            onChange={(event) => setChosen(event.target.value)}
            value={chosen}
          >
            {members.map((member) => (
              <option key={member.id} value={member.id}>
                {label(member)}
              </option>
            ))}
          </NativeSelect>
          <Problem text={problem} />
        </Field>
      }
      finalFocus={finalFocus}
      onConfirm={async () => {
        setProblem(undefined);
        try {
          await updatePerson(staffId, { membership_id: chosen });
          const member = members.find((item) => item.id === chosen);
          if (member) onLinked(member);
          return undefined;
        } catch (error) {
          return problemText(error, t("failed"), t("forbidden"));
        }
      }}
      onOpenChange={onOpenChange}
      open={open}
      title={t("linkTitle", { name })}
    />
  );
}
