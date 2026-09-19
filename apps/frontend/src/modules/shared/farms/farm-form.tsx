"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import type { Farm, FarmInput } from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { Textarea } from "@saas-core/ui/components/textarea";

type Values = Required<
  Pick<
    FarmInput,
    | "name"
    | "herd_number"
    | "tax_id"
    | "village"
    | "address"
    | "keeper_name"
    | "email"
    | "phone"
    | "notes"
  >
>;

const FIELDS = [
  "herd_number",
  "tax_id",
  "village",
  "address",
  "keeper_name",
  "phone",
  "email",
] as const;

/** One form for adding and editing a farm; the server normalizes numbers. */
export function FarmForm({
  farm,
  submitLabel,
  onSubmit,
}: {
  farm?: Farm;
  submitLabel: string;
  /** `changed` holds only the edited fields: an edit sends just those, so two
   * people changing different fields of one farm do not undo each other. */
  onSubmit: (
    values: Values,
    changed: Partial<Values>,
  ) => Promise<string | undefined>;
}) {
  const t = useTranslations("Farms");
  const schema = useMemo(
    () =>
      z.object({
        name: z.string().trim().min(2, t("nameRequired")),
        herd_number: z.string(),
        tax_id: z.string(),
        village: z.string(),
        address: z.string(),
        keeper_name: z.string(),
        email: z.union([z.literal(""), z.email(t("invalidEmail"))]),
        phone: z.string(),
        notes: z.string(),
      }),
    [t],
  );
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: farm?.name ?? "",
      herd_number: farm?.herd_number ?? "",
      tax_id: farm?.tax_id ?? "",
      village: farm?.village ?? "",
      address: farm?.address ?? "",
      keeper_name: farm?.keeper_name ?? "",
      email: farm?.email ?? "",
      phone: farm?.phone ?? "",
      notes: farm?.notes ?? "",
    },
  });

  async function submit(values: Values) {
    const dirty = form.formState.dirtyFields;
    const changed = Object.fromEntries(
      Object.entries(values).filter(([key]) => dirty[key as keyof Values]),
    ) as Partial<Values>;
    const problem = await onSubmit(values, changed);
    if (problem) form.setError("root", { type: "server", message: problem });
  }

  return (
    <form className="space-y-4" noValidate onSubmit={form.handleSubmit(submit)}>
      <FieldGroup>
        <Field data-invalid={Boolean(form.formState.errors.name)}>
          <FieldLabel htmlFor="farm-name">{t("name")}</FieldLabel>
          <Input id="farm-name" {...form.register("name")} />
          <FieldError errors={[form.formState.errors.name]} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          {FIELDS.map((name) => (
            <Field
              data-invalid={Boolean(form.formState.errors[name])}
              key={name}
            >
              <FieldLabel htmlFor={`farm-${name}`}>{t(name)}</FieldLabel>
              <Input
                id={`farm-${name}`}
                type={name === "email" ? "email" : "text"}
                {...form.register(name)}
              />
              {name === "herd_number" ? (
                <FieldDescription>{t("herdNumberHint")}</FieldDescription>
              ) : null}
              <FieldError errors={[form.formState.errors[name]]} />
            </Field>
          ))}
        </div>
        <Field>
          <FieldLabel htmlFor="farm-notes">{t("notes")}</FieldLabel>
          <Textarea id="farm-notes" rows={3} {...form.register("notes")} />
        </Field>
      </FieldGroup>
      {form.formState.errors.root ? (
        <p className="text-sm text-destructive" role="alert">
          {form.formState.errors.root.message}
        </p>
      ) : null}
      <Button disabled={form.formState.isSubmitting} type="submit">
        {form.formState.isSubmitting ? t("saving") : submitLabel}
      </Button>
    </form>
  );
}
