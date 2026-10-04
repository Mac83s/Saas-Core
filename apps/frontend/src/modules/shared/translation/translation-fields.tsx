"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import type { TranslationUnitState } from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { Textarea } from "@saas-core/ui/components/textarea";

type Tone = "success" | "warning" | "info" | "destructive";

/** ADR-057 pkt 9: current is green, what needs doing amber, a fact blue. */
const TONES: Record<string, Tone> = {
  fresh: "success",
  stale: "warning",
  missing: "warning",
  copied: "warning",
  unverified: "info",
  blocked: "destructive",
};

/**
 * One language of an item, unit by unit (TL12d): the source text read-only
 * above its field, the state of the translation and who wrote it. The card,
 * the booking items and later pages (TL15) and the centre (TL16) share it.
 */
export function TranslationFields({
  units,
  values,
  onChange,
  labelFor,
  multiline = () => false,
  noteFor,
  disabled = false,
  idPrefix,
}: {
  units: TranslationUnitState[];
  /** The texts being edited, by unit key. */
  values: Record<string, string>;
  onChange: (key: string, text: string) => void;
  labelFor: (key: string) => string;
  multiline?: (key: string) => boolean;
  /** What else a unit has to say under its field, e.g. a text that waits. */
  noteFor?: (key: string) => ReactNode;
  disabled?: boolean;
  idPrefix: string;
}) {
  const t = useTranslations("Translations");
  return (
    <div className="space-y-5">
      {units.map((unit) => {
        const id = `${idPrefix}-${unit.key.replaceAll("/", "-")}`;
        const Control = multiline(unit.key) ? Textarea : Input;
        return (
          <Field key={unit.key}>
            <FieldLabel htmlFor={id}>{labelFor(unit.key)}</FieldLabel>
            <p
              className="text-sm text-muted-foreground wrap-anywhere"
              id={`${id}-source`}
            >
              {unit.source_text}
            </p>
            <Control
              aria-describedby={`${id}-source ${id}-state`}
              disabled={disabled}
              id={id}
              onChange={(event) => onChange(unit.key, event.target.value)}
              value={values[unit.key] ?? ""}
            />
            <p
              className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"
              id={`${id}-state`}
            >
              <Badge variant={TONES[unit.status] ?? "warning"}>
                {t(`status_${unit.status}` as "status_fresh")}
              </Badge>
              {unit.origin
                ? t(`origin_${unit.origin}` as "origin_human")
                : null}
            </p>
            {noteFor?.(unit.key)}
          </Field>
        );
      })}
    </div>
  );
}
