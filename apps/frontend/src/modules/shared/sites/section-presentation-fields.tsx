"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { useFormContext, type UseFormReturn } from "react-hook-form";

import {
  isRichTextAnchor,
  richTextAnchors,
  type SectionPresentationV1,
  type SectionPresentationV2,
  type SiteBlock,
} from "@saas-core/site-blocks";
import { Button } from "@saas-core/ui/components/button";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

const OPTIONS = {
  inner: ["standard", "narrow", "wide", "full"],
  surface: ["default", "muted", "accent", "inverse"],
} as const;

type PresentationField = keyof typeof OPTIONS;

/** Controlled, like the decoration fields: no nested form or save of its own.
 *  The first option of each list is how an untouched section renders. Every
 *  write is the v2 envelope; nothing left set at all is `undefined`. */
export function SectionPresentationFields({
  value,
  onChange,
  blockIndex,
  disabled = false,
}: {
  value?: SectionPresentationV1 | SectionPresentationV2;
  onChange: (value: SectionPresentationV2 | undefined) => void;
  /** This section's position in the form's `blocks`, so its own anchor is
   *  not counted as taken. Without a page form nothing can collide. */
  blockIndex?: number;
  disabled?: boolean;
}) {
  const t = useTranslations("Sites.sectionPresentation");
  const richText = useTranslations("Sites.richText");
  const id = useId();
  const form = useFormContext() as UseFormReturn | null;
  const stored = (value && "anchor" in value ? value.anchor : undefined) ?? "";
  // An invalid anchor stays in the input and is never written; a change from
  // outside (reset, undo) replaces what was typed.
  const [typed, setTyped] = useState(stored);
  const [seen, setSeen] = useState(stored);
  if (stored !== seen) {
    setSeen(stored);
    setTyped(stored);
  }

  function write(field: PresentationField | "anchor", option: string) {
    if (disabled) return;
    const next: Record<string, unknown> = { ...value, [field]: option };
    delete next.schemaVersion;
    if (option === "") delete next[field];
    onChange(
      Object.keys(next).length
        ? ({ ...next, schemaVersion: 2 } as SectionPresentationV2)
        : undefined,
    );
  }

  function update(field: PresentationField, option: string) {
    // A forged change event must not become persisted presentation data.
    if ((OPTIONS[field] as readonly string[]).includes(option))
      write(field, option);
  }

  // Section and heading anchors share one namespace on the page.
  const blocks = (form?.getValues("blocks") ?? []) as SiteBlock[];
  const anchorError =
    typed === ""
      ? undefined
      : !isRichTextAnchor(typed)
        ? richText("anchorInvalid")
        : richTextAnchors(
              blocks.map((block, index) =>
                index === blockIndex
                  ? { ...block, presentation: undefined }
                  : block,
              ),
            ).includes(typed)
          ? richText("anchorTaken")
          : undefined;

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
      <Field data-invalid={Boolean(anchorError)}>
        <FieldLabel htmlFor={`${id}-anchor`}>{t("fields.anchor")}</FieldLabel>
        <Input
          aria-describedby={`${id}-anchor-hint${anchorError ? ` ${id}-anchor-error` : ""}`}
          aria-invalid={Boolean(anchorError)}
          autoCapitalize="none"
          id={`${id}-anchor`}
          onChange={(event) => {
            const next = event.target.value;
            setTyped(next);
            if (next === "" || isRichTextAnchor(next)) write("anchor", next);
          }}
          spellCheck={false}
          value={typed}
        />
        <FieldDescription id={`${id}-anchor-hint`}>
          {t("hints.anchor")}
          {stored && (
            <>
              {" "}
              {t("anchorLink")}{" "}
              <code className="select-all rounded bg-muted px-1">
                #{stored}
              </code>
            </>
          )}
        </FieldDescription>
        <FieldError id={`${id}-anchor-error`}>{anchorError}</FieldError>
      </Field>
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
