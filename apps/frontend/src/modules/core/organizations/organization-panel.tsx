"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ComponentProps } from "react";
import { useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  Controller,
  useForm,
  type Control,
  type FieldValues,
  type Path,
  type SubmitHandler,
  type UseFormReturn,
} from "react-hook-form";
import {
  Building2Icon,
  PlusIcon,
  RefreshCwIcon,
  UserPlusIcon,
} from "lucide-react";
import { z } from "zod";

import {
  ApiProblemError,
  createInvitation,
  createOrganization,
  listInvitations,
  listMemberships,
  listRoles,
  type RoleCatalog,
  listOrganizations,
  revokeInvitation,
  selectActiveOrganization,
  updateCurrentOrganization,
  updateMembership,
  type InvitationSummary,
  type MembershipSummary,
  type OrganizationSummary,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
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
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@saas-core/ui/components/select";

import { useRouter } from "#i18n/navigation";
import { selfSignupTypes, typeText } from "#lib/organization-types";
import { RolesCard } from "./roles-card";
import { organizationErrorMessage } from "./problem";

const TIMEZONES =
  typeof Intl.supportedValuesOf === "function"
    ? Intl.supportedValuesOf("timeZone")
    : ["Europe/Warsaw", "Europe/London", "America/New_York", "Asia/Tokyo"];
const CURRENCIES = ["PLN", "EUR", "USD", "GBP"] as const;

type CreateValues = {
  name: string;
  slug: string;
  workspace_kind: "personal" | "business";
  organization_type: string;
  default_locale: "pl" | "en";
  timezone: string;
  currency: string;
};
type SettingsValues = Pick<
  CreateValues,
  "name" | "default_locale" | "timezone" | "currency"
>;
type InviteValues = { email: string; role: string };
type RoleOption = readonly [string, string];

export function OrganizationPanel() {
  const t = useTranslations("Organizations");
  const common = useTranslations("Common");
  const locale = useLocale();
  const router = useRouter();
  const [organizations, setOrganizations] = useState<OrganizationSummary[]>([]);
  const [members, setMembers] = useState<MembershipSummary[]>([]);
  const [invitations, setInvitations] = useState<InvitationSummary[]>([]);
  const [roleCatalog, setRoleCatalog] = useState<RoleCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState<string>();
  const [createOpen, setCreateOpen] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const active = organizations.find((item) => item.active);
  const canReadMembers = active && active.role !== "viewer";
  const canManageMembers =
    active && ["manager", "admin", "owner"].includes(active.role);
  const canManageSettings = active && ["admin", "owner"].includes(active.role);
  // Roles come from the organization's type and its own (ADR-050); core's
  // translated names are used where a key has one.
  const roleName = (key: string): string =>
    GLOBAL_ROLE_KEYS.has(key)
      ? roleLabel(t, key)
      : (roleCatalog?.roles.find((role) => role.key === key)?.name ?? key);
  const roleOptions = (limitedOnly: boolean): RoleOption[] =>
    (roleCatalog?.roles ?? [])
      .filter((role) => role.key !== "owner" && (!limitedOnly || role.limited))
      .map((role) => [role.key, roleName(role.key)] as const);

  const createSchema = useMemo(
    () =>
      z.object({
        name: z.string().min(2, t("required")),
        slug: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, t("invalidSlug")),
        workspace_kind: z.enum(["personal", "business"]),
        organization_type: z.string().min(1),
        default_locale: z.enum(["pl", "en"]),
        timezone: z.string().min(1, t("required")),
        currency: z.string().regex(/^[A-Z]{3}$/),
      }),
    [t],
  );
  const inviteSchema = useMemo(
    () =>
      z.object({
        email: z.email(t("invalidEmail")),
        role: z.string().min(1),
      }),
    [t],
  );
  const createForm = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      name: "",
      slug: "",
      workspace_kind: "business",
      organization_type: selfSignupTypes[0]?.key ?? "",
      default_locale: locale === "en" ? "en" : "pl",
      timezone: "Europe/Warsaw",
      currency: "PLN",
    },
  });
  const settingsForm = useForm<SettingsValues>();
  const inviteForm = useForm<InviteValues>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { email: "", role: "staff" },
  });

  const load = useCallback(async () => {
    setLoading(true);
    setProblem(undefined);
    try {
      const data = await fetchOrganizationData();
      setOrganizations(data.organizations);
      setMembers(data.members);
      setInvitations(data.invitations);
      setRoleCatalog(data.roles);
    } catch (error) {
      if (error instanceof ApiProblemError && error.problem.status === 403) {
        router.replace("/login");
        return;
      }
      setProblem(organizationErrorMessage(error, t("problem")));
    } finally {
      setLoading(false);
    }
  }, [router, t]);

  useEffect(() => {
    let mounted = true;
    void fetchOrganizationData()
      .then((data) => {
        if (!mounted) return;
        setOrganizations(data.organizations);
        setMembers(data.members);
        setInvitations(data.invitations);
        setRoleCatalog(data.roles);
      })
      .catch((error: unknown) => {
        if (!mounted) return;
        if (error instanceof ApiProblemError && error.problem.status === 403) {
          router.replace("/login");
          return;
        }
        setProblem(organizationErrorMessage(error, t("problem")));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [router, t]);

  useEffect(() => {
    if (!active) return;
    settingsForm.reset({
      name: active.name,
      default_locale: active.default_locale === "en" ? "en" : "pl",
      timezone: active.timezone,
      currency: active.currency,
    });
  }, [active, settingsForm]);

  async function switchOrganization(organization: OrganizationSummary | null) {
    if (!organization || organization.active) return;
    setSwitching(true);
    setProblem(undefined);
    try {
      await selectActiveOrganization(organization.id);
      await load();
      router.refresh();
    } catch (error) {
      setProblem(organizationErrorMessage(error, t("problem")));
    } finally {
      setSwitching(false);
    }
  }

  async function submitCreate(values: CreateValues) {
    setProblem(undefined);
    try {
      await createOrganization(values);
      setCreateOpen(false);
      createForm.reset();
      await load();
      router.refresh();
    } catch (error) {
      setProblem(organizationErrorMessage(error, t("problem")));
    }
  }

  async function submitSettings(values: SettingsValues) {
    if (!active) return;
    setProblem(undefined);
    try {
      await updateCurrentOrganization({ ...values, version: active.version });
      await load();
    } catch (error) {
      setProblem(organizationErrorMessage(error, t("problem")));
    }
  }

  async function submitInvitation(values: InviteValues) {
    setProblem(undefined);
    try {
      await createInvitation(values);
      setInviteOpen(false);
      inviteForm.reset();
      await load();
    } catch (error) {
      setProblem(organizationErrorMessage(error, t("problem")));
    }
  }

  async function changeRole(member: MembershipSummary, role: string | null) {
    if (!role || role === member.role) return;
    setProblem(undefined);
    try {
      await updateMembership(member.id, { role });
      await load();
    } catch (error) {
      setProblem(organizationErrorMessage(error, t("problem")));
    }
  }

  async function revokePendingInvitation(id: string) {
    setProblem(undefined);
    try {
      await revokeInvitation(id);
      await load();
    } catch (error) {
      setProblem(organizationErrorMessage(error, t("problem")));
    }
  }

  return (
    <section className="space-y-6" aria-labelledby="organizations-heading">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <h2 className="text-xl font-semibold" id="organizations-heading">
            {t("title")}
          </h2>
          <p className="text-sm text-muted-foreground">{t("description")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            aria-label={common("refresh")}
            onClick={() => void load()}
            size="icon"
            variant="outline"
          >
            <RefreshCwIcon
              aria-hidden="true"
              className={loading ? "animate-spin" : ""}
            />
          </Button>
          <CreateOrganizationDialog
            common={common}
            form={createForm}
            locale={locale}
            onOpenChange={setCreateOpen}
            onSubmit={submitCreate}
            open={createOpen}
            t={t}
          />
        </div>
      </div>

      {problem && <Problem message={problem} />}

      <Card>
        <CardContent className="grid gap-4 pt-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <Field>
            <FieldLabel htmlFor="organization-switcher">
              {t("choose")}
            </FieldLabel>
            <Combobox
              disabled={loading || switching}
              isItemEqualToValue={(item, value) => item.id === value.id}
              itemToStringLabel={(item) => item.name}
              itemToStringValue={(item) => item.id}
              items={organizations}
              onValueChange={(value) => void switchOrganization(value)}
              value={active ?? null}
            >
              <ComboboxInput
                className="w-full"
                id="organization-switcher"
                placeholder={t("search")}
              />
              <ComboboxContent>
                <ComboboxEmpty>{t("empty")}</ComboboxEmpty>
                <ComboboxList>
                  {organizations.map((organization) => (
                    <ComboboxItem key={organization.id} value={organization}>
                      <Building2Icon aria-hidden="true" />
                      <span className="flex-1 truncate">
                        {organization.name}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {roleLabel(t, organization.role)}
                      </span>
                    </ComboboxItem>
                  ))}
                </ComboboxList>
              </ComboboxContent>
            </Combobox>
          </Field>
          {active && (
            <Badge variant="secondary">
              {t("active")}: {active.slug}
            </Badge>
          )}
        </CardContent>
      </Card>

      {active && (
        <div className="grid gap-6 xl:grid-cols-2">
          {canManageSettings && (
            <SettingsCard
              common={common}
              form={settingsForm}
              locale={locale}
              onSubmit={submitSettings}
              t={t}
            />
          )}
          {canReadMembers && (
            <MembersCard
              activeRole={active.role}
              canManage={Boolean(canManageMembers)}
              locale={locale}
              members={members}
              onRoleChange={changeRole}
              roleName={roleName}
              roleOptions={roleOptions}
              t={t}
            />
          )}
          {canReadMembers && (
            <InvitationsCard
              canManage={Boolean(canManageMembers)}
              common={common}
              form={inviteForm}
              invitations={invitations}
              inviteOpen={inviteOpen}
              locale={locale}
              onInviteOpenChange={setInviteOpen}
              onRevoke={revokePendingInvitation}
              onSubmit={submitInvitation}
              roleName={roleName}
              roleOptions={roleOptions}
              t={t}
            />
          )}
          {canReadMembers && roleCatalog && (
            <RolesCard
              canManage={Boolean(canManageSettings)}
              catalog={roleCatalog}
              onChanged={load}
            />
          )}
        </div>
      )}
    </section>
  );
}

type Translator = ReturnType<typeof useTranslations<"Organizations">>;
type CommonTranslator = ReturnType<typeof useTranslations<"Common">>;

async function fetchOrganizationData(): Promise<{
  organizations: OrganizationSummary[];
  members: MembershipSummary[];
  invitations: InvitationSummary[];
  roles: RoleCatalog | null;
}> {
  const organizations = await listOrganizations();
  const selected = organizations.find((item) => item.active);
  if (!selected || selected.role === "viewer") {
    return { organizations, members: [], invitations: [], roles: null };
  }
  const [members, invitations, roles] = await Promise.all([
    listMemberships(),
    listInvitations(),
    listRoles(),
  ]);
  return { organizations, members, invitations, roles };
}

function CreateOrganizationDialog({
  open,
  onOpenChange,
  form,
  onSubmit,
  locale,
  t,
  common,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  form: UseFormReturn<CreateValues>;
  onSubmit: SubmitHandler<CreateValues>;
  locale: string;
  t: Translator;
  common: CommonTranslator;
}) {
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogTrigger render={<Button />}>
        <PlusIcon aria-hidden="true" /> {t("create")}
      </DialogTrigger>
      <DialogContent closeLabel={common("close")}>
        <DialogHeader>
          <DialogTitle>{t("createTitle")}</DialogTitle>
          <DialogDescription>{t("createDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)}>
          <FieldGroup>
            <TextField form={form} label={t("name")} name="name" />
            <TextField form={form} label={t("slug")} name="slug" />
            {selfSignupTypes.length > 1 ? (
              <SelectField
                control={form.control}
                label={t("organizationType")}
                name="organization_type"
                options={selfSignupTypes.map((type) => [
                  type.key,
                  typeText(type.label, locale),
                ])}
              />
            ) : null}
            <SelectField
              control={form.control}
              label={t("kind")}
              name="workspace_kind"
              options={[
                ["business", t("business")],
                ["personal", t("personal")],
              ]}
            />
            <SelectField
              control={form.control}
              label={t("locale")}
              name="default_locale"
              options={[
                ["pl", common("polish")],
                ["en", common("english")],
              ]}
            />
            <TimezoneField control={form.control} locale={locale} t={t} />
            <SelectField
              control={form.control}
              label={t("currency")}
              name="currency"
              options={CURRENCIES.map((currency) => [
                currency,
                currencyLabel(currency, locale),
              ])}
            />
          </FieldGroup>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button disabled={form.formState.isSubmitting} type="submit">
              {form.formState.isSubmitting ? t("creating") : t("create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function SettingsCard({
  form,
  onSubmit,
  locale,
  t,
  common,
}: {
  form: UseFormReturn<SettingsValues>;
  onSubmit: SubmitHandler<SettingsValues>;
  locale: string;
  t: Translator;
  common: CommonTranslator;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings")}</CardTitle>
        <CardDescription>{t("settingsDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)}>
          <TextField form={form} label={t("name")} name="name" />
          <div className="grid gap-4 sm:grid-cols-2">
            <SelectField
              control={form.control}
              label={t("locale")}
              name="default_locale"
              options={[
                ["pl", common("polish")],
                ["en", common("english")],
              ]}
            />
            <SelectField
              control={form.control}
              label={t("currency")}
              name="currency"
              options={CURRENCIES.map((currency) => [
                currency,
                currencyLabel(currency, locale),
              ])}
            />
          </div>
          <TimezoneField control={form.control} locale={locale} t={t} />
          <Button disabled={form.formState.isSubmitting} type="submit">
            {common("save")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function MembersCard({
  members,
  canManage,
  activeRole,
  roleName,
  roleOptions,
  onRoleChange,
  locale,
  t,
}: {
  members: MembershipSummary[];
  canManage: boolean;
  activeRole: string;
  onRoleChange: (
    member: MembershipSummary,
    role: string | null,
  ) => Promise<void>;
  roleName: (key: string) => string;
  roleOptions: (limitedOnly: boolean) => RoleOption[];
  locale: string;
  t: Translator;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("members")}</CardTitle>
        <CardDescription>{t("membersDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {members.length === 0 && (
          <p className="text-sm text-muted-foreground">{t("noMembers")}</p>
        )}
        {members.map((member: MembershipSummary) => {
          const roles = roleOptions(activeRole === "manager");
          const manageable =
            canManage &&
            member.role !== "owner" &&
            (activeRole !== "manager" ||
              roles.some(([key]) => key === member.role));
          return (
            <div
              className="flex flex-col gap-3 rounded-lg border p-3 sm:flex-row sm:items-center"
              key={member.id}
            >
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{member.email}</p>
                <p className="text-xs text-muted-foreground">
                  {t("joined")}: {formatDate(member.joined_at, locale)}
                </p>
              </div>
              {manageable ? (
                <Select
                  onValueChange={(role) => void onRoleChange(member, role)}
                  value={member.role}
                >
                  <SelectTrigger
                    aria-label={`${t("role")}: ${member.email}`}
                    size="sm"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {roles.map(([key, label]) => (
                      <SelectItem key={key} value={key}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Badge variant="outline">{roleName(member.role)}</Badge>
              )}
              <Badge variant="secondary">{statusLabel(t, member.status)}</Badge>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function InvitationsCard({
  invitations,
  canManage,
  inviteOpen,
  roleName,
  roleOptions,
  onInviteOpenChange,
  form,
  onSubmit,
  onRevoke,
  locale,
  t,
  common,
}: {
  invitations: InvitationSummary[];
  canManage: boolean;
  inviteOpen: boolean;
  onInviteOpenChange: (open: boolean) => void;
  form: UseFormReturn<InviteValues>;
  onSubmit: SubmitHandler<InviteValues>;
  onRevoke: (id: string) => Promise<void>;
  roleName: (key: string) => string;
  roleOptions: (limitedOnly: boolean) => RoleOption[];
  locale: string;
  t: Translator;
  common: CommonTranslator;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>{t("invitations")}</CardTitle>
          <CardDescription>{t("inviteDescription")}</CardDescription>
        </div>
        {canManage && (
          <Dialog onOpenChange={onInviteOpenChange} open={inviteOpen}>
            <DialogTrigger render={<Button size="sm" />}>
              <UserPlusIcon aria-hidden="true" />
              {t("invite")}
            </DialogTrigger>
            <DialogContent closeLabel={common("close")}>
              <DialogHeader>
                <DialogTitle>{t("invite")}</DialogTitle>
                <DialogDescription>{t("inviteDescription")}</DialogDescription>
              </DialogHeader>
              <form
                className="space-y-4"
                onSubmit={form.handleSubmit(onSubmit)}
              >
                <TextField
                  form={form}
                  label={t("email")}
                  name="email"
                  type="email"
                />
                <SelectField
                  control={form.control}
                  label={t("role")}
                  name="role"
                  options={roleOptions(false)}
                />
                <DialogFooter>
                  <DialogClose render={<Button variant="outline" />}>
                    {common("cancel")}
                  </DialogClose>
                  <Button disabled={form.formState.isSubmitting} type="submit">
                    {form.formState.isSubmitting
                      ? t("sending")
                      : t("sendInvitation")}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {invitations.length === 0 && (
          <p className="text-sm text-muted-foreground">{t("noInvitations")}</p>
        )}
        {invitations.map((invitation: InvitationSummary) => (
          <div
            className="flex items-center gap-3 rounded-lg border p-3"
            key={invitation.id}
          >
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium">{invitation.email}</p>
              <p className="text-xs text-muted-foreground">
                {roleName(invitation.role)} · {t("expires")}:{" "}
                {formatDate(invitation.expires_at, locale)}
              </p>
            </div>
            <Badge variant="secondary">
              {statusLabel(t, invitation.status)}
            </Badge>
            {canManage && invitation.status === "pending" && (
              <Button
                onClick={() => void onRevoke(invitation.id)}
                size="sm"
                variant="outline"
              >
                {t("revoke")}
              </Button>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function TextField<T extends FieldValues>({
  form,
  name,
  label,
  ...props
}: {
  form: UseFormReturn<T>;
  name: Path<T>;
  label: string;
  type?: ComponentProps<typeof Input>["type"];
}) {
  const fieldError = form.getFieldState(name, form.formState).error?.message;
  const error = typeof fieldError === "string" ? fieldError : undefined;
  return (
    <Field data-invalid={Boolean(error)}>
      <FieldLabel htmlFor={name}>{label}</FieldLabel>
      <Input
        aria-invalid={Boolean(error)}
        id={name}
        {...form.register(name)}
        {...props}
      />
      <FieldError>{error}</FieldError>
    </Field>
  );
}

function SelectField<T extends FieldValues>({
  control,
  name,
  label,
  options,
}: {
  control: Control<T>;
  name: Path<T>;
  label: string;
  options: readonly (readonly [string, string])[];
}) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => (
        <Field data-invalid={fieldState.invalid}>
          <FieldLabel htmlFor={name}>{label}</FieldLabel>
          <Select
            onValueChange={field.onChange}
            value={typeof field.value === "string" ? field.value : null}
          >
            <SelectTrigger
              aria-invalid={fieldState.invalid}
              className="w-full"
              id={name}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {options.map(([value, text]) => (
                <SelectItem key={value} value={value}>
                  {text}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <FieldError>{fieldState.error?.message}</FieldError>
        </Field>
      )}
    />
  );
}

function TimezoneField<T extends FieldValues>({
  control,
  locale,
  t,
}: {
  control: Control<T>;
  locale: string;
  t: Translator;
}) {
  return (
    <Controller
      control={control}
      name={"timezone" as Path<T>}
      render={({ field, fieldState }) => (
        <Field data-invalid={fieldState.invalid}>
          <FieldLabel htmlFor="timezone">{t("timezone")}</FieldLabel>
          <Combobox
            items={TIMEZONES}
            onValueChange={(value) => field.onChange(value ?? "")}
            value={typeof field.value === "string" ? field.value : null}
          >
            <ComboboxInput
              className="w-full"
              id="timezone"
              placeholder={t("timezoneSearch")}
            />
            <ComboboxContent>
              <ComboboxEmpty>{t("timezoneEmpty")}</ComboboxEmpty>
              <ComboboxList>
                {TIMEZONES.map((zone) => (
                  <ComboboxItem key={zone} value={zone}>
                    {timeZoneLabel(zone, locale)}
                  </ComboboxItem>
                ))}
              </ComboboxList>
            </ComboboxContent>
          </Combobox>
          <FieldError>{fieldState.error?.message}</FieldError>
        </Field>
      )}
    />
  );
}

function Problem({ message }: { message: string }) {
  return (
    <div
      className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
      role="alert"
    >
      {message}
    </div>
  );
}

const GLOBAL_ROLE_KEYS = new Set([
  "owner",
  "admin",
  "manager",
  "staff",
  "viewer",
]);

function roleLabel(t: Translator, role: string): string {
  const keys = {
    owner: "owner",
    admin: "admin",
    manager: "manager",
    staff: "staff",
    viewer: "viewer",
  } as const;
  return role in keys ? t(keys[role as keyof typeof keys]) : role;
}

function statusLabel(t: Translator, status: string): string {
  const keys = {
    onboarding: "onboarding",
    suspended: "suspended",
    archived: "archived",
    pending: "pending",
    accepted: "accepted",
    revoked: "revoked",
    expired: "expired",
    active: "active",
  } as const;
  return status in keys ? t(keys[status as keyof typeof keys]) : status;
}

function formatDate(value: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function currencyLabel(currency: string, locale: string): string {
  const name = new Intl.DisplayNames(locale, { type: "currency" }).of(currency);
  return name ? `${name} (${currency})` : currency;
}

function timeZoneLabel(timeZone: string, locale: string): string {
  const offset = new Intl.DateTimeFormat(locale, {
    timeZone,
    timeZoneName: "longOffset",
  })
    .formatToParts(new Date())
    .find((part) => part.type === "timeZoneName")?.value;
  const name = timeZone.replaceAll("_", " ");
  return offset ? `${name} (${offset})` : name;
}
