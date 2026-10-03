"use client";

import { useContext, useId, useState } from "react";
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

import { PageEditorContext } from "./page-editor-context";
import { SegmentedOptions } from "./segmented-options";

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
  // The swatches are painted by the site's own palette and style.
  const look = useContext(PageEditorContext)?.look ?? "site-theme";
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

  const inner = value?.inner ?? OPTIONS.inner[0];
  const surface = value?.surface ?? OPTIONS.surface[0];

  return (
    // No box of its own: a legend on a border breaks across it in the
    // inspector's narrow column.
    <FieldSet
      aria-describedby={`${id}-description`}
      className="min-w-0 gap-4"
      disabled={disabled}
    >
      <FieldLegend variant="label" className="font-semibold">
        {t("title")}
      </FieldLegend>
      <p className="text-sm text-muted-foreground" id={`${id}-description`}>
        {t("description")}
      </p>
      <FieldSet aria-describedby={`${id}-inner-hint`} className="min-w-0 gap-2">
        <FieldLegend variant="label">{t("fields.inner")}</FieldLegend>
        <SegmentedOptions
          label={(option) => t(`options.inner.${option}`)}
          onChange={(option) => update("inner", option)}
          options={OPTIONS.inner}
          value={inner}
        />
        <FieldDescription id={`${id}-inner-hint`}>
          {t(`hints.inner.${inner}`)}
        </FieldDescription>
      </FieldSet>
      <FieldSet
        aria-describedby={`${id}-surface-hint`}
        className="min-w-0 gap-2"
      >
        <FieldLegend variant="label">{t("fields.surface")}</FieldLegend>
        <div className="grid grid-cols-2 gap-1.5">
          {OPTIONS.surface.map((option) => (
            <Button
              key={option}
              type="button"
              variant="outline"
              size="sm"
              className="h-11 min-w-0 justify-start gap-2 px-2 text-xs font-medium aria-pressed:border-primary aria-pressed:ring-1 aria-pressed:ring-primary pointer-fine:h-9"
              aria-pressed={option === surface}
              onClick={() => update("surface", option)}
            >
              <span
                aria-hidden="true"
                className={`${look} site-theme--preview studio-swatch`}
              >
                <span
                  className={
                    option === "default"
                      ? undefined
                      : `site-presentation--surface-${option}`
                  }
                />
              </span>
              <span className="min-w-0 truncate">
                {t(`options.surface.${option}`)}
              </span>
            </Button>
          ))}
        </div>
        <FieldDescription id={`${id}-surface-hint`}>
          {t(`hints.surface.${surface}`)}
        </FieldDescription>
      </FieldSet>
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
