"use client";

/** Who may write one surface's content (ADR-035 §4a).
 *
 *  Three settings, not a switch, because the useful answer for most clients is
 *  the middle one: let the automation write, keep the decision to publish. The
 *  endpoints behind this refuse API keys, so the value can only ever be changed
 *  by a person — an integration that could widen its own reach would make the
 *  whole setting decorative.
 */

import { useTranslations } from "next-intl";

import type { AutomationPolicy } from "@saas-core/api-client";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { NativeSelect } from "@saas-core/ui/components/native-select";

const POLICIES: readonly AutomationPolicy[] = [
  "manual",
  "proposed",
  "automated",
];

const HINT: Record<AutomationPolicy, string> = {
  manual: "automationManualHint",
  proposed: "automationProposedHint",
  automated: "automationAutomatedHint",
};

const LABEL: Record<AutomationPolicy, string> = {
  manual: "automationManual",
  proposed: "automationProposed",
  automated: "automationAutomated",
};

export function AutomationPolicyField({
  busy,
  id,
  onChange,
  value,
}: {
  busy: boolean;
  id: string;
  onChange: (policy: AutomationPolicy) => void;
  value: string;
}) {
  const t = useTranslations("Sites");
  const current = isPolicy(value) ? value : "manual";

  return (
    <div className="space-y-2 rounded-lg border p-3">
      <Field>
        <FieldLabel htmlFor={id}>{t("automationTitle")}</FieldLabel>
        <NativeSelect
          disabled={busy}
          id={id}
          onChange={(event) => {
            const next = event.target.value;
            if (isPolicy(next) && next !== current) onChange(next);
          }}
          value={current}
        >
          {POLICIES.map((policy) => (
            <option key={policy} value={policy}>
              {t(LABEL[policy])}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <p className="text-sm text-muted-foreground">{t(HINT[current])}</p>
    </div>
  );
}

function isPolicy(value: string): value is AutomationPolicy {
  return (POLICIES as readonly string[]).includes(value);
}
