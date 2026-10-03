"use client";

import type { SiteLocalizationReport } from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@saas-core/ui/components/select";
import { useTranslations } from "next-intl";
import { useId } from "react";

import type { CompanyLocale } from "../../../lib/company-locales";

/** A language's state on one page, as the readiness report names it (W8),
 *  plus the page's own language. */
export type LanguageState =
  | "source"
  | "published"
  | "complete"
  | "missing"
  | "pending"
  | "outdated"
  | "untranslated"
  | "incomplete";

export interface LanguageOption {
  readonly locale: string;
  readonly name: string;
  readonly state: LanguageState;
}

/** The page's languages: the site's own first, then the company's others,
 *  each with its state on this page. */
export function pageLanguageOptions(
  report: SiteLocalizationReport | undefined,
  pageId: string,
  locales: readonly CompanyLocale[],
): LanguageOption[] {
  const source = report?.default_locale ?? locales[0]?.code ?? "pl";
  const states = new Map(
    (report?.pages.find((item) => item.page_id === pageId)?.locales ?? []).map(
      (item) => [item.locale, item.state],
    ),
  );
  const names = new Map(locales.map((item) => [item.code, item.name]));
  const codes = [
    source,
    ...(report?.languages ?? locales.map((item) => ({ locale: item.code })))
      .map((item) => item.locale)
      .filter((code) => code !== source),
  ];
  return [...new Set(codes)].map((locale) => ({
    locale,
    name: names.get(locale) ?? locale.toUpperCase(),
    state:
      locale === source
        ? "source"
        : ((states.get(locale) as LanguageState | undefined) ?? "missing"),
  }));
}

const TONE: Record<LanguageState, "success" | "warning" | "neutral"> = {
  source: "neutral",
  published: "success",
  complete: "success",
  missing: "neutral",
  pending: "warning",
  outdated: "warning",
  untranslated: "warning",
  incomplete: "warning",
};

/** A language version's state as a badge — the same words and colours
 *  wherever a version is listed (the switch, an article's versions). */
export function TranslationStatusBadge({ state }: { state: LanguageState }) {
  const t = useTranslations("Sites.languageMode");
  return <Badge variant={TONE[state]}>{t(`states.${state}`)}</Badge>;
}

/** Which language of the page the editor shows (TL15). A Select: a company
 *  has two to five languages, each with its state beside its name. */
export function LanguageSwitch({
  value,
  options,
  onChange,
  disabled = false,
}: {
  value: string;
  options: readonly LanguageOption[];
  onChange: (locale: string) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("Sites.languageMode");
  const id = useId();
  if (options.length < 2) return null;
  return (
    <Field className="w-auto sm:min-w-56">
      <FieldLabel htmlFor={id} className="sr-only">
        {t("switchLabel")}
      </FieldLabel>
      <Select
        value={value}
        disabled={disabled}
        onValueChange={(next) => {
          if (typeof next === "string" && next !== value) onChange(next);
        }}
      >
        <SelectTrigger id={id} size="sm" aria-label={t("switchLabel")}>
          <SelectValue>
            {(current: string) => {
              const option = options.find((item) => item.locale === current);
              if (!option) return current;
              // A phone keeps the toolbar to one row: the name only.
              return (
                <>
                  <span>{option.name}</span>
                  <span className="max-sm:hidden">
                    {" "}
                    — {t(`states.${option.state}`)}
                  </span>
                </>
              );
            }}
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.locale} value={option.locale}>
              <span>{option.name}</span>
              <TranslationStatusBadge state={option.state} />
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  );
}
