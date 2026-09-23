"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import {
  siteGoogleFonts,
  type PagePresentationV1,
  type SiteFont,
} from "@saas-core/site-blocks";
import { Button } from "@saas-core/ui/components/button";
import {
  Field,
  FieldDescription,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { NativeSelect } from "@saas-core/ui/components/native-select";

// The appearance editor's order: web fonts first, then system stacks.
const FONTS: readonly SiteFont[] = [
  ...(Object.keys(siteGoogleFonts) as (keyof typeof siteGoogleFonts)[]),
  "system",
  "arial",
  "georgia",
  "trebuchet",
  "verdana",
];

const OPTIONS = {
  width: ["full"],
  headingFont: FONTS,
  bodyFont: FONTS,
} as const;

type PresentationField = keyof typeof OPTIONS;

/** Fonts are named as in the site appearance editor. */
function useFontLabel() {
  const appearance = useTranslations("Sites.appearance");
  return (font: string) =>
    font in siteGoogleFonts
      ? siteGoogleFonts[font as keyof typeof siteGoogleFonts]
      : appearance(`options.${font}`);
}

/** One page's own look, stored with the page draft. Controlled: the draft
 *  form owns the value, so undo, dirty state and the exit guard cover it.
 *  An empty choice means "as the site"; nothing chosen at all is `null`. */
export function PagePresentationFields({
  value,
  onChange,
  disabled = false,
}: {
  value: PagePresentationV1 | null;
  onChange: (value: PagePresentationV1 | null) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("Sites.pagePresentation");
  const fontLabel = useFontLabel();
  const id = useId();

  function update(field: PresentationField, option: string) {
    if (
      disabled ||
      (option !== "" && !(OPTIONS[field] as readonly string[]).includes(option))
    )
      return;
    const next: PagePresentationV1 = { ...value, schemaVersion: 1 };
    if (option === "") delete next[field];
    else Object.assign(next, { [field]: option });
    onChange(Object.keys(next).length > 1 ? next : null);
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
      {(Object.keys(OPTIONS) as PresentationField[]).map((field) => (
        <Field key={field}>
          <FieldLabel htmlFor={`${id}-${field}`}>
            {t(`fields.${field}`)}
          </FieldLabel>
          <NativeSelect
            aria-describedby={`${id}-${field}-hint`}
            id={`${id}-${field}`}
            onChange={(event) => update(field, event.target.value)}
            value={value?.[field] ?? ""}
          >
            <option value="">{t("asSite")}</option>
            {OPTIONS[field].map((option) => (
              <option key={option} value={option}>
                {field === "width" ? t("fullWidth") : fontLabel(option)}
              </option>
            ))}
          </NativeSelect>
          <FieldDescription id={`${id}-${field}-hint`}>
            {t(`hints.${field}`)}
          </FieldDescription>
        </Field>
      ))}
      <Button
        disabled={disabled || value === null}
        onClick={() => onChange(null)}
        type="button"
        variant="outline"
      >
        {t("reset")}
      </Button>
    </FieldSet>
  );
}

/** A one-line description for review screens: "Full width · Headings: Lora". */
export function PagePresentationSummary({ value }: { value: unknown }) {
  const t = useTranslations("Sites.pagePresentation");
  const fontLabel = useFontLabel();
  const presentation = (value ?? {}) as Partial<PagePresentationV1>;
  const parts = [
    presentation.width === "full" ? t("fullWidth") : "",
    presentation.headingFont
      ? t("summaryHeadingFont", {
          font: fontLabel(presentation.headingFont),
        })
      : "",
    presentation.bodyFont
      ? t("summaryBodyFont", { font: fontLabel(presentation.bodyFont) })
      : "",
  ].filter(Boolean);
  return <>{parts.length ? parts.join(" · ") : t("asSite")}</>;
}
