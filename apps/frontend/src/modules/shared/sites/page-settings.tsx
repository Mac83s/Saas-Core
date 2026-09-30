"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  setPageAutomationPolicy,
  setPageType,
  type PageSummary,
  type PageTypeValue,
} from "@saas-core/api-client";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { AutomationPolicyField } from "./automation-policy";
import { sitesErrorMessage } from "./problem";

/** The eight types W9.6.2 fixes, in the order an operator thinks about a
 *  site: the front page first, the legal pages last. */
const PAGE_TYPES: readonly PageTypeValue[] = [
  "homepage",
  "landing",
  "service",
  "about",
  "contact",
  "article_index",
  "article",
  "legal",
];

/** What kind of page this is, in the vocabulary SEO tooling uses.
 *
 *  Nothing about the page renders differently — the type is what an optimiser
 *  reasons about, and one told that the contact page is a landing page will
 *  rewrite it like one. */
export function PageTypeField({
  onChanged,
  page,
}: {
  onChanged: (page: PageSummary) => void;
  page: PageSummary;
}) {
  const t = useTranslations("Sites");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  return (
    <div className="space-y-2 rounded-lg border p-3">
      <Field>
        <FieldLabel htmlFor="page-type">{t("pageTypeLabel")}</FieldLabel>
        <NativeSelect
          disabled={busy}
          id="page-type"
          onChange={(event) => {
            const next = event.target.value as PageTypeValue;
            setBusy(true);
            setProblem(undefined);
            void setPageType(page.id, next)
              .then(onChanged)
              .catch((error: unknown) => {
                setProblem(sitesErrorMessage(error, t));
              })
              .finally(() => {
                setBusy(false);
              });
          }}
          value={page.page_type}
        >
          {PAGE_TYPES.map((value) => (
            <option key={value} value={value}>
              {t(`pageType_${value}`)}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <p className="text-sm text-muted-foreground">{t("pageTypeHint")}</p>
      {problem && (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      )}
    </div>
  );
}

/** ADR-035 §4a: what an automation may do with this page is a person's
 *  decision. The endpoint behind the field refuses API keys, so the field is
 *  the only way the value changes. */
export function PageAutomationSwitch({
  onChanged,
  page,
}: {
  onChanged: (page: PageSummary) => void;
  page: PageSummary;
}) {
  const t = useTranslations("Sites");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  return (
    <div className="space-y-2">
      <AutomationPolicyField
        busy={busy}
        id="page-policy"
        onChange={(policy) => {
          setBusy(true);
          setProblem(undefined);
          void setPageAutomationPolicy(page.id, policy)
            .then(onChanged)
            .catch((error: unknown) => {
              setProblem(sitesErrorMessage(error, t));
            })
            .finally(() => {
              setBusy(false);
            });
        }}
        value={page.automation_policy}
      />
      {page.draft_author === "automation" && (
        <p className="text-sm" role="status">
          {t("pageProposalWaiting")}
        </p>
      )}
      {problem && (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      )}
    </div>
  );
}
