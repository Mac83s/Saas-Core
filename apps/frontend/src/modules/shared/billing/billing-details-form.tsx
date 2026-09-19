"use client";

import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  Controller,
  useForm,
  type Control,
  type FieldValues,
  type Path,
  type UseFormReturn,
} from "react-hook-form";
import { LoaderCircleIcon } from "lucide-react";
import { z } from "zod";

import {
  ApiProblemError,
  updateBillingDetails,
  type BillingDetailsState,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
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

// Where Stripe Tax is registered for us, plus the neighbours a Polish company
// actually invoices. Names come from the browser in the reader's own language,
// so the list needs codes only.
const COUNTRIES = [
  "AT",
  "BE",
  "BG",
  "CH",
  "CY",
  "CZ",
  "DE",
  "DK",
  "EE",
  "ES",
  "FI",
  "FR",
  "GB",
  "GR",
  "HR",
  "HU",
  "IE",
  "IT",
  "LT",
  "LU",
  "LV",
  "MT",
  "NL",
  "NO",
  "PL",
  "PT",
  "RO",
  "SE",
  "SI",
  "SK",
] as const;

type Country = { code: string; name: string };

export function BillingDetailsForm({
  details,
  canManage,
  onSaved,
}: {
  details: BillingDetailsState;
  canManage: boolean;
  onSaved: (saved: BillingDetailsState) => void;
}) {
  const t = useTranslations("CustomerBilling");
  const locale = useLocale();
  const [saved, setSaved] = useState(false);
  const [problem, setProblem] = useState<string | undefined>(undefined);

  const schema = useMemo(
    () =>
      z.object({
        customer_kind: z.enum(["company", "individual"]),
        legal_name: z.string().trim().min(1, t("detailsRequired")),
        tax_id: z.string().trim().max(32),
        country_code: z.string().trim().length(2, t("detailsRequired")),
        address_line1: z.string().trim().min(1, t("detailsRequired")),
        postal_code: z.string().trim().min(1, t("detailsRequired")),
        city: z.string().trim().min(1, t("detailsRequired")),
        billing_email: z.email(t("detailsEmailInvalid")),
      }),
    [t],
  );
  type Values = z.infer<typeof schema>;

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      customer_kind: details.customer_kind,
      legal_name: details.legal_name,
      tax_id: details.tax_id,
      country_code: details.country_code || "PL",
      address_line1: details.address_line1,
      postal_code: details.postal_code,
      city: details.city,
      billing_email: details.billing_email,
    },
  });

  const countries = useMemo<Country[]>(() => {
    const names = new Intl.DisplayNames([locale], { type: "region" });
    return COUNTRIES.map((code) => ({
      code,
      name: names.of(code) ?? code,
    })).sort((a, b) => a.name.localeCompare(b.name, locale));
  }, [locale]);

  async function save(values: Values) {
    setProblem(undefined);
    setSaved(false);
    try {
      onSaved(await updateBillingDetails(values));
      setSaved(true);
    } catch (error) {
      setProblem(
        error instanceof ApiProblemError &&
          typeof error.problem.detail === "string"
          ? error.problem.detail
          : t("checkoutUnavailable"),
      );
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>{t("detailsTitle")}</h2>
        </CardTitle>
        <CardDescription>{t("detailsDescription")}</CardDescription>
      </CardHeader>
      <form onSubmit={form.handleSubmit(save)}>
        <CardContent>
          {details.missing.length > 0 ? (
            <p className="mb-4 text-sm font-medium text-warning-foreground">
              {t("detailsMissing")}
            </p>
          ) : null}
          <FieldGroup className="sm:grid sm:grid-cols-2 sm:gap-4">
            <SelectField
              control={form.control}
              label={t("customerKind")}
              name="customer_kind"
              options={[
                ["company", t("customerKindCompany")],
                ["individual", t("customerKindIndividual")],
              ]}
            />
            <TextField form={form} label={t("legalName")} name="legal_name" />
            <TextField form={form} label={t("taxId")} name="tax_id" />
            <TextField
              form={form}
              label={t("billingEmail")}
              name="billing_email"
              type="email"
            />
            <CountryField
              control={form.control}
              countries={countries}
              label={t("country")}
              name="country_code"
            />
            <TextField
              form={form}
              label={t("addressLine1")}
              name="address_line1"
            />
            <TextField form={form} label={t("postalCode")} name="postal_code" />
            <TextField form={form} label={t("city")} name="city" />
          </FieldGroup>
          {problem ? (
            <p className="mt-4 text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          {saved ? (
            <p className="mt-4 text-sm text-muted-foreground" role="status">
              {t("detailsSaved")}
            </p>
          ) : null}
        </CardContent>
        <CardFooter>
          <Button
            disabled={!canManage || form.formState.isSubmitting}
            type="submit"
          >
            {form.formState.isSubmitting ? (
              <LoaderCircleIcon aria-hidden="true" className="animate-spin" />
            ) : null}
            {canManage ? t("saveDetails") : t("ownerOnly")}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}

function TextField<T extends FieldValues>({
  form,
  name,
  label,
  type,
}: {
  form: UseFormReturn<T>;
  name: Path<T>;
  label: string;
  type?: string;
}) {
  const fieldError = form.getFieldState(name, form.formState).error?.message;
  const error = typeof fieldError === "string" ? fieldError : undefined;
  return (
    <Field data-invalid={Boolean(error)}>
      <FieldLabel htmlFor={name}>{label}</FieldLabel>
      <Input
        aria-invalid={Boolean(error)}
        id={name}
        type={type}
        {...form.register(name)}
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

// ADR-020: thirty entries is a filterable set, so a combobox rather than a
// select — and the customer types the country name, not its code.
function CountryField<T extends FieldValues>({
  control,
  name,
  label,
  countries,
}: {
  control: Control<T>;
  name: Path<T>;
  label: string;
  countries: Country[];
}) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => {
        const selected =
          countries.find((country) => country.code === field.value) ?? null;
        return (
          <Field data-invalid={fieldState.invalid}>
            <FieldLabel htmlFor={name}>{label}</FieldLabel>
            <Combobox
              isItemEqualToValue={(item, value) => item?.code === value?.code}
              itemToStringLabel={(item) => item?.name ?? ""}
              itemToStringValue={(item) => item?.code ?? ""}
              items={countries}
              onValueChange={(value: Country | null) =>
                field.onChange(value?.code ?? "")
              }
              value={selected}
            >
              <ComboboxInput
                aria-invalid={fieldState.invalid}
                className="w-full"
                id={name}
              />
              <ComboboxContent>
                <ComboboxEmpty />
                <ComboboxList>
                  {countries.map((country) => (
                    <ComboboxItem key={country.code} value={country}>
                      {country.name}
                    </ComboboxItem>
                  ))}
                </ComboboxList>
              </ComboboxContent>
            </Combobox>
            <FieldError>{fieldState.error?.message}</FieldError>
          </Field>
        );
      }}
    />
  );
}
