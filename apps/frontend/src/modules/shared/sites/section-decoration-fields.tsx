"use client";

import { useId } from "react";
import { useLocale, useTranslations } from "next-intl";

import {
  sectionDecorationPresets,
  type SectionDecorationV1,
} from "@saas-core/site-blocks";
import { Button } from "@saas-core/ui/components/button";
import {
  Field,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { NativeSelect } from "@saas-core/ui/components/native-select";

const OPTIONS = {
  background: ["none", "tint", "gradient", "grid", "dots"],
  frame: ["none", "outline", "accent", "double"],
  ornament: ["none", "orbs", "rings", "wave", "botanical", "sparkles"],
  placement: ["top_right", "bottom_left", "both"],
  intensity: ["subtle", "soft"],
  motion: ["none", "drift", "breathe"],
} as const;

type DecorationField = keyof typeof OPTIONS;

const DEFAULTS = {
  background: "none",
  frame: "none",
  ornament: "none",
  placement: "top_right",
  intensity: "subtle",
  motion: "none",
} as const satisfies Required<Omit<SectionDecorationV1, "schemaVersion">>;

/** Controlled fields for the existing block form: no nested form or separate
 * save action. Optional values stay optional until the person changes them. */
export function SectionDecorationFields({
  value,
  onChange,
  disabled = false,
}: {
  value?: SectionDecorationV1;
  onChange: (value: SectionDecorationV1 | undefined) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("Sites.decorations");
  const id = useId();
  const locale = useLocale() === "en" ? "en" : "pl";
  const hasOrnament = (value?.ornament ?? DEFAULTS.ornament) !== "none";
  const selectedPreset = value
    ? sectionDecorationPresets.find((preset) =>
        (Object.keys(OPTIONS) as DecorationField[]).every(
          (field) =>
            (value[field] ?? DEFAULTS[field]) ===
            (preset.decoration[field] ?? DEFAULTS[field]),
        ),
      )
    : undefined;

  function update(field: DecorationField, option: string) {
    // Native options are controlled, but do not turn a forged change event
    // into arbitrary persisted decoration data.
    if (
      disabled ||
      (field === "motion" && !hasOrnament) ||
      !(OPTIONS[field] as readonly string[]).includes(option)
    )
      return;
    onChange({ ...value, schemaVersion: 1, [field]: option });
  }

  function select(field: DecorationField, description?: string) {
    return (
      <Field>
        <FieldLabel htmlFor={`${id}-${field}`}>
          {t(`fields.${field}`)}
        </FieldLabel>
        <NativeSelect
          aria-describedby={description}
          id={`${id}-${field}`}
          disabled={disabled || (field === "motion" && !hasOrnament)}
          onChange={(event) => update(field, event.target.value)}
          value={value?.[field] ?? DEFAULTS[field]}
        >
          {OPTIONS[field].map((option) => (
            <option key={option} value={option}>
              {t(`options.${field}.${option}`)}
            </option>
          ))}
        </NativeSelect>
      </Field>
    );
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
      <p aria-live="polite" className="text-xs text-muted-foreground">
        {t(value ? "custom" : "default")}
      </p>
      <Field>
        <FieldLabel htmlFor={`${id}-preset`}>{t("preset")}</FieldLabel>
        <NativeSelect
          aria-describedby={
            selectedPreset ? `${id}-preset-description` : undefined
          }
          id={`${id}-preset`}
          value={selectedPreset?.id ?? ""}
          onChange={(event) => {
            const preset = sectionDecorationPresets.find(
              (item) => item.id === event.target.value,
            );
            if (!disabled && preset) onChange({ ...preset.decoration });
          }}
        >
          <option value="" disabled>
            {t("presetPlaceholder")}
          </option>
          {sectionDecorationPresets.map((preset) => (
            <option key={preset.id} value={preset.id}>
              {preset.labels[locale].name}
            </option>
          ))}
        </NativeSelect>
        {selectedPreset ? (
          <p
            className="text-xs text-muted-foreground"
            id={`${id}-preset-description`}
          >
            {selectedPreset.labels[locale].description}
          </p>
        ) : null}
      </Field>
      <FieldSet className="min-w-0 border-t pt-3">
        <FieldLegend variant="label">{t("groups.background")}</FieldLegend>
        {select("background")}
      </FieldSet>
      <FieldSet className="min-w-0 border-t pt-3">
        <FieldLegend variant="label">{t("groups.frame")}</FieldLegend>
        {select("frame")}
      </FieldSet>
      <FieldSet className="min-w-0 border-t pt-3">
        <FieldLegend variant="label">{t("groups.ornament")}</FieldLegend>
        {select("ornament")}
        {select("placement")}
        {select("intensity")}
      </FieldSet>
      <FieldSet className="min-w-0 border-t pt-3">
        <FieldLegend variant="label">{t("groups.motion")}</FieldLegend>
        {select("motion", `${id}-motion-description`)}
        <p
          className="text-xs leading-relaxed text-muted-foreground"
          id={`${id}-motion-description`}
        >
          {!hasOrnament ? <>{t("motionUnavailable")} </> : null}
          {t("motionHint")}
        </p>
      </FieldSet>
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
