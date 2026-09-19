"use client";

import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  updateCurrentOrganization,
  type OrganizationSummary,
} from "@saas-core/api-client";
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
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { useRouter } from "#i18n/navigation";

const TIMEZONES =
  typeof Intl.supportedValuesOf === "function"
    ? Intl.supportedValuesOf("timeZone")
    : ["Europe/Warsaw", "Europe/London", "America/New_York", "Asia/Tokyo"];
const CURRENCIES = ["PLN", "EUR", "USD", "GBP"];

type Values = {
  name: string;
  default_locale: "pl" | "en";
  timezone: string;
  currency: string;
};

function formValues(organization: OrganizationSummary): Values {
  return {
    name: organization.name,
    default_locale: organization.default_locale === "en" ? "en" : "pl",
    timezone: organization.timezone,
    currency: organization.currency,
  };
}

/**
 * The company's own details (Settings › Company): its name and the language,
 * time zone and currency new data starts from. The schedule's working hours
 * are read in this time zone.
 */
export function OrganizationSettings({
  organization,
}: {
  organization: OrganizationSummary;
}) {
  const t = useTranslations("Settings");
  const common = useTranslations("Common");
  const locale = useLocale();
  const router = useRouter();
  // Every save moves the version the next one has to name (optimistic lock).
  const [version, setVersion] = useState(organization.version);
  const [saved, setSaved] = useState(false);
  const schema = useMemo(
    () =>
      z.object({
        name: z.string().trim().min(2, t("nameRequired")).max(160),
        default_locale: z.enum(["pl", "en"]),
        timezone: z.string().min(1, t("timezoneRequired")),
        currency: z.string().regex(/^[A-Z]{3}$/),
      }),
    [t],
  );
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: formValues(organization),
  });
  const { errors, dirtyFields, isSubmitting } = form.formState;
  // A company may already use a currency outside the usual four.
  const currencies = CURRENCIES.includes(organization.currency)
    ? CURRENCIES
    : [...CURRENCIES, organization.currency];

  async function submit(values: Values) {
    setSaved(false);
    // Only what changed: the audit lists the fields a save touched.
    const changes = Object.fromEntries(
      Object.entries(values).filter(
        ([key]) => dirtyFields[key as keyof Values],
      ),
    ) as Partial<Values>;
    if (Object.keys(changes).length === 0) {
      setSaved(true);
      return;
    }
    try {
      const updated = await updateCurrentOrganization({ ...changes, version });
      setVersion(updated.version);
      form.reset(formValues(updated));
      setSaved(true);
      // The name is in the menu too, which the server renders.
      router.refresh();
    } catch (error) {
      form.setError("root", {
        type: "server",
        message: !(error instanceof ApiProblemError)
          ? t("saveError")
          : error.problem.code === "organization_version_conflict"
            ? t("conflict")
            : error.message,
      });
    }
  }

  return (
    <Card>
      <CardContent>
        <form
          className="space-y-6"
          noValidate
          onSubmit={form.handleSubmit(submit)}
        >
          <FieldGroup>
            <Field data-invalid={Boolean(errors.name)}>
              <FieldLabel htmlFor="organization-name">
                {t("companyName")}
              </FieldLabel>
              <Input
                aria-invalid={Boolean(errors.name)}
                autoComplete="organization"
                id="organization-name"
                {...form.register("name")}
              />
              <FieldError errors={[errors.name]} />
            </Field>
            <div className="grid gap-5 sm:grid-cols-2">
              <Field>
                <FieldLabel htmlFor="organization-locale">
                  {t("defaultLanguage")}
                </FieldLabel>
                <NativeSelect
                  id="organization-locale"
                  {...form.register("default_locale")}
                >
                  <option value="pl">{common("polish")}</option>
                  <option value="en">{common("english")}</option>
                </NativeSelect>
              </Field>
              <Field>
                <FieldLabel htmlFor="organization-currency">
                  {t("currency")}
                </FieldLabel>
                <NativeSelect
                  id="organization-currency"
                  {...form.register("currency")}
                >
                  {currencies.map((code) => (
                    <option key={code} value={code}>
                      {currencyLabel(code, locale)}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
            </div>
            <Controller
              control={form.control}
              name="timezone"
              render={({ field, fieldState }) => (
                <Field data-invalid={fieldState.invalid}>
                  <FieldLabel htmlFor="organization-timezone">
                    {t("timezone")}
                  </FieldLabel>
                  <Combobox
                    items={TIMEZONES}
                    onValueChange={(value) => field.onChange(value ?? "")}
                    value={field.value || null}
                  >
                    <ComboboxInput
                      aria-describedby="organization-timezone-hint"
                      aria-invalid={fieldState.invalid}
                      className="w-full"
                      id="organization-timezone"
                      placeholder={t("timezoneSearch")}
                      triggerLabel={t("timezoneShow")}
                    />
                    <ComboboxContent>
                      <ComboboxEmpty>{t("timezoneEmpty")}</ComboboxEmpty>
                      <ComboboxList>
                        {(zone: string) => (
                          <ComboboxItem key={zone} value={zone}>
                            {timeZoneLabel(zone, locale)}
                          </ComboboxItem>
                        )}
                      </ComboboxList>
                    </ComboboxContent>
                  </Combobox>
                  <FieldDescription id="organization-timezone-hint">
                    {t("timezoneHint")}
                  </FieldDescription>
                  <FieldError errors={[fieldState.error]} />
                </Field>
              )}
            />
          </FieldGroup>
          {errors.root ? (
            <p className="text-sm text-destructive" role="alert">
              {errors.root.message}
            </p>
          ) : null}
          <p aria-live="polite" className="text-sm text-muted-foreground">
            {saved ? t("companySaved") : null}
          </p>
          <Button disabled={isSubmitting} type="submit">
            {isSubmitting ? t("saving") : t("save")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
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
