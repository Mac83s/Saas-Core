"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import type { SectionPresentationV1 } from "@saas-core/site-blocks";
import { Button } from "@saas-core/ui/components/button";
import {
  Field,
  FieldDescription,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { NativeSelect } from "@saas-core/ui/components/native-select";

const OPTIONS = {
  inner: ["standard", "narrow", "wide", "full"],
  surface: ["default", "muted", "accent", "inverse"],
} as const;

type PresentationField = keyof typeof OPTIONS;

/** Controlled, like the decoration fields: no nested form or save of its own.
 *  The first option of each list is how an untouched section renders. */
export function SectionPresentationFields({
  value,
  onChange,
  disabled = false,
}: {
  value?: SectionPresentationV1;
  onChange: (value: SectionPresentationV1 | undefined) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("Sites.sectionPresentation");
  const id = useId();

  function update(field: PresentationField, option: string) {
    // A forged change event must not become persisted presentation data.
    if (disabled || !(OPTIONS[field] as readonly string[]).includes(option))
      return;
    onChange({ ...value, schemaVersion: 1, [field]: option });
  }

  return (
    <FieldSet
      aria-describedby={`${id}-description`}
      className="min-w-0 gap-4 rounded-lg border p-4"
      disabled={disabled}
    >
      <FieldLegend className="px-1">{t("title")}</FieldLegend>
      <p className="text-sm text-muted-foreground" id={`${id}-description`}>
        {t("description")}
      </p>
      {(Object.keys(OPTIONS) as PresentationField[]).map((field) => {
        const current = value?.[field] ?? OPTIONS[field][0];
        return (
          <Field key={field}>
            <FieldLabel htmlFor={`${id}-${field}`}>
              {t(`fields.${field}`)}
            </FieldLabel>
            <NativeSelect
              aria-describedby={`${id}-${field}-hint`}
              id={`${id}-${field}`}
              onChange={(event) => update(field, event.target.value)}
              value={current}
            >
              {OPTIONS[field].map((option) => (
                <option key={option} value={option}>
                  {t(`options.${field}.${option}`)}
                </option>
              ))}
            </NativeSelect>
            <FieldDescription id={`${id}-${field}-hint`}>
              {t(`hints.${field}.${current}`)}
            </FieldDescription>
          </Field>
        );
      })}
      <Button
        disabled={disabled || value === undefined}
        onClick={() => onChange(undefined)}
        type="button"
        variant="outline"
      >
        {t("reset")}
      </Button>
    </FieldSet>
  );
}
