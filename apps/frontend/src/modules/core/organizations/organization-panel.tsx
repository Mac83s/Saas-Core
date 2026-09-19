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
import { Building2Icon, PlusIcon, RefreshCwIcon } from "lucide-react";
import { z } from "zod";

import {
  ApiProblemError,
  createOrganization,
  listOrganizations,
  selectActiveOrganization,
  type OrganizationSummary,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import { Card, CardContent } from "@saas-core/ui/components/card";
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

/** The person's organizations. The active one's team is TeamPanel's. */
export function OrganizationPanel() {
  const t = useTranslations("Organizations");
  const common = useTranslations("Common");
  const locale = useLocale();
  const router = useRouter();
  const [organizations, setOrganizations] = useState<OrganizationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState<string>();
  const [createOpen, setCreateOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const active = organizations.find((item) => item.active);

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

  const load = useCallback(async () => {
    setLoading(true);
    setProblem(undefined);
    try {
      setOrganizations(await listOrganizations());
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
    void listOrganizations()
      .then((data) => {
        if (mounted) setOrganizations(data);
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
    </section>
  );
}

type Translator = ReturnType<typeof useTranslations<"Organizations">>;
type CommonTranslator = ReturnType<typeof useTranslations<"Common">>;

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
      <DialogTrigger render={<Button variant="outline" />}>
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
