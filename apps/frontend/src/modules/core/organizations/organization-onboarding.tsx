"use client";

import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { ApiProblemError, createOrganization } from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
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

import { useRouter } from "#i18n/navigation";
import { selfSignupTypes, typeText } from "#lib/organization-types";
import { slugFromName } from "./slug";

type Values = { name: string; organizationType: string };

/**
 * The first screen after sign-in for an account without an organization:
 * who you are and what your organization is called (ADR-050). The type decides
 * what the panel offers, so it is asked before the panel opens.
 */
export function OrganizationOnboarding() {
  const t = useTranslations("Onboarding");
  const locale = useLocale();
  const router = useRouter();
  const [problem, setProblem] = useState<string>();
  const schema = useMemo(
    () =>
      z.object({
        name: z.string().trim().min(2, t("nameRequired")),
        organizationType: z.string().min(1),
      }),
    [t],
  );
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: "",
      organizationType: selfSignupTypes[0]?.key ?? "",
    },
  });
  const chosen = useWatch({ control: form.control, name: "organizationType" });

  async function submit(values: Values) {
    setProblem(undefined);
    try {
      await createOrganization({
        name: values.name.trim(),
        slug: slugFromName(values.name),
        organization_type: values.organizationType,
        workspace_kind: "business",
        default_locale: locale === "en" ? "en" : "pl",
        timezone:
          Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Warsaw",
        currency: "PLN",
      });
      router.replace("/panel");
      router.refresh();
    } catch (error) {
      setProblem(
        error instanceof ApiProblemError &&
          typeof error.problem.detail === "string"
          ? error.problem.detail
          : t("failed"),
      );
    }
  }

  return (
    <form className="space-y-6" noValidate onSubmit={form.handleSubmit(submit)}>
      <FieldGroup>
        {selfSignupTypes.length > 1 ? (
          <FieldSet>
            <FieldLegend>{t("whoAreYou")}</FieldLegend>
            <div className="grid gap-3 sm:grid-cols-2">
              {selfSignupTypes.map((type) => (
                <label
                  className="flex cursor-pointer flex-col gap-1 rounded-xl border p-4 has-[:checked]:border-primary has-[:checked]:bg-primary/5 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-ring"
                  key={type.key}
                >
                  <span className="flex items-center gap-2 font-medium">
                    <input
                      className="size-4 accent-[var(--primary)]"
                      type="radio"
                      value={type.key}
                      {...form.register("organizationType")}
                    />
                    {typeText(type.label, locale)}
                  </span>
                  {type.description ? (
                    <span className="text-sm text-muted-foreground">
                      {typeText(type.description, locale)}
                    </span>
                  ) : null}
                </label>
              ))}
            </div>
          </FieldSet>
        ) : null}
        <Field data-invalid={Boolean(form.formState.errors.name)}>
          <FieldLabel htmlFor="organization-name">{t("name")}</FieldLabel>
          <Input
            aria-invalid={Boolean(form.formState.errors.name)}
            autoComplete="organization"
            id="organization-name"
            {...form.register("name")}
          />
          <FieldDescription>
            {t("nameHint", {
              type: typeText(
                selfSignupTypes.find((type) => type.key === chosen)?.label ??
                  null,
                locale,
              ),
            })}
          </FieldDescription>
          <FieldError errors={[form.formState.errors.name]} />
        </Field>
      </FieldGroup>
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      <Button
        className="w-full"
        disabled={form.formState.isSubmitting}
        type="submit"
      >
        {form.formState.isSubmitting ? t("creating") : t("create")}
      </Button>
    </form>
  );
}
