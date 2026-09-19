"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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
import { LoaderCircleIcon, PencilIcon } from "lucide-react";
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

/**
 * The invoice details ADR-040 requires before the first purchase. While they
 * are missing the form is open, because the plans cannot be bought without it;
 * once complete they fold into a summary, edited on request.
 */
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
  const incomplete = details.missing.length > 0;
  const [editing, setEditing] = useState(canManage && incomplete);
  const [saved, setSaved] = useState(false);
  const [problem, setProblem] = useState<string | undefined>(undefined);
  const editButton = useRef<HTMLButtonElement>(null);
  // Set by the person's own switch between summary and form: the control they
  // used disappears, so focus follows them to the other side.
  const moveFocus = useRef(false);

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

  useEffect(() => {
    if (!moveFocus.current) return;
    moveFocus.current = false;
    if (editing) form.setFocus("legal_name");
    else editButton.current?.focus();
  }, [editing, form]);

  function toggle(open: boolean) {
    moveFocus.current = true;
    setSaved(false);
    setProblem(undefined);
    if (!open) form.reset();
    setEditing(open);
  }

  async function save(values: Values) {
    setProblem(undefined);
    setSaved(false);
    try {
      const next = await updateBillingDetails(values);
      onSaved(next);
      form.reset(values);
      setSaved(true);
      if (next.missing.length === 0) {
        moveFocus.current = true;
        setEditing(false);
      }
    } catch (error) {
      setProblem(
        error instanceof ApiProblemError &&
          typeof error.problem.detail === "string"
          ? error.problem.detail
          : t("detailsSaveError"),
      );
    }
  }

  const country = details.country_code
    ? new Intl.DisplayNames([locale], { type: "region" }).of(
        details.country_code,
      )
    : "";
  const address = [
    details.address_line1,
    [details.postal_code, details.city].filter(Boolean).join(" "),
    country,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <section aria-labelledby="billing-details-heading">
      <Card>
        <CardHeader>
          <CardTitle>
            <h2 id="billing-details-heading">{t("detailsTitle")}</h2>
          </CardTitle>
          <CardDescription>{t("detailsDescription")}</CardDescription>
        </CardHeader>
        {editing ? (
          <form
            noValidate
            onSubmit={(event) => void form.handleSubmit(save)(event)}
          >
            <CardContent>
              {incomplete ? (
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
                <TextField
                  form={form}
                  label={t("legalName")}
                  name="legal_name"
                />
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
                <TextField
                  form={form}
                  label={t("postalCode")}
                  name="postal_code"
                />
                <TextField form={form} label={t("city")} name="city" />
              </FieldGroup>
              {problem ? (
                <p className="mt-4 text-sm text-destructive" role="alert">
                  {problem}
                </p>
              ) : null}
            </CardContent>
            <CardFooter className="mt-4 flex-wrap gap-3">
              <Button disabled={form.formState.isSubmitting} type="submit">
                {form.formState.isSubmitting ? (
                  <LoaderCircleIcon
                    aria-hidden="true"
                    className="animate-spin"
                  />
                ) : null}
                {t("saveDetails")}
              </Button>
              {incomplete ? null : (
                <Button
                  onClick={() => toggle(false)}
                  type="button"
                  variant="ghost"
                >
                  {t("cancelEdit")}
                </Button>
              )}
            </CardFooter>
          </form>
        ) : (
          <>
            <CardContent className="space-y-4">
              <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
                <SummaryRow
                  label={t("buyer")}
                  value={[
                    t(
                      details.customer_kind === "individual"
                        ? "customerKindIndividual"
                        : "customerKindCompany",
                    ),
                    details.legal_name,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                />
                <SummaryRow label={t("taxId")} value={details.tax_id} />
                <SummaryRow label={t("address")} value={address} />
                <SummaryRow
                  label={t("billingEmail")}
                  value={details.billing_email}
                />
              </dl>
              {saved ? (
                <p className="text-sm text-success-foreground" role="status">
                  {t("detailsSaved")}
                </p>
              ) : null}
            </CardContent>
            <CardFooter className="flex-wrap gap-3">
              {canManage ? (
                <Button
                  onClick={() => toggle(true)}
                  ref={editButton}
                  type="button"
                  variant="outline"
                >
                  <PencilIcon aria-hidden="true" />
                  {t("editDetails")}
                </Button>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t("detailsOwnerOnly")}
                </p>
              )}
            </CardFooter>
          </>
        )}
      </Card>
    </section>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium break-words">{value || "—"}</dd>
    </div>
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
