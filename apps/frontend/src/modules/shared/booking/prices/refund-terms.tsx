"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { PlusIcon, Trash2Icon } from "lucide-react";

import {
  ApiProblemError,
  updateSetupService,
  type ServiceSetup,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import { Field, FieldDescription } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { Switch } from "@saas-core/ui/components/switch";

import { refusal } from "./price-dialog";

/** The bounds the API serves for an offer's thresholds
 *  (`GET /booking/setup/options/`, `refund_thresholds`). */
const MAX_ROWS = 6;
const MAX_DAYS = 365;
/** The server's refusals the panel says in its own language. */
const REFUSALS = ["thresholds_not_descending", "duplicate_threshold"];

type Row = { days: string; percent: string };

/**
 * What a customer who gives a booking up gets back (ADR-072 §8, phase 4h):
 * the offer's refund thresholds — „at least N days before the start → so
 * many percent back” — and, where a part is paid ahead, whether they are
 * counted on that part only or on everything paid (owner decision 28a).
 * Saved on its own, like every part of „Cennik”.
 */
export function RefundTerms({
  deposit,
  onSetupChanged,
  service,
}: {
  /** The offer asks for a part ahead: the switch has something to say. */
  deposit: boolean;
  onSetupChanged: () => Promise<void> | void;
  service: ServiceSetup;
}) {
  const t = useTranslations("PriceList");
  const [rows, setRows] = useState<Row[]>(
    (service.cancellation_refunds ?? []).map((row) => ({
      days: String(row.min_days_before),
      percent: String(row.refund_percent),
    })),
  );
  const [everything, setEverything] = useState(
    service.cancellation_applies_to === "paid",
  );
  const [problem, setProblem] = useState<string>();
  const [notice, setNotice] = useState("");

  function change(index: number, next: Partial<Row>) {
    setRows((current) =>
      current.map((row, at) => (at === index ? { ...row, ...next } : row)),
    );
  }

  async function save() {
    setProblem(undefined);
    setNotice("");
    const thresholds = rows.map((row) => ({
      min_days_before: Number(row.days),
      refund_percent: Number(row.percent),
    }));
    const whole = (value: number, most: number) =>
      Number.isInteger(value) && value >= 0 && value <= most;
    if (
      rows.some((row) => row.days.trim() === "" || row.percent.trim() === "") ||
      thresholds.some(
        (row) =>
          !whole(row.min_days_before, MAX_DAYS) ||
          !whole(row.refund_percent, 100),
      )
    )
      return setProblem(t("refundRowInvalid", { days: MAX_DAYS }));
    try {
      await updateSetupService(
        service.id,
        {
          cancellation_refunds: thresholds,
          cancellation_applies_to: everything ? "paid" : "deposit",
          expected_version: service.version,
        },
        crypto.randomUUID(),
      );
      setNotice(t("refundSaved"));
      // As the server keeps them: the longest notice first.
      setRows((current) =>
        [...current].sort((a, b) => Number(b.days) - Number(a.days)),
      );
    } catch (error) {
      const code =
        error instanceof ApiProblemError
          ? error.problem.errors?.[0]?.code
          : undefined;
      setProblem(
        code && REFUSALS.includes(code)
          ? t(`refundRefused_${code}`)
          : refusal(error, t("failed"), t("versionConflict")),
      );
    }
    await onSetupChanged();
  }

  return (
    <section aria-labelledby="offer-refund-terms" className="space-y-3">
      <h3 className="font-medium" id="offer-refund-terms">
        {t("refundTitle")}
      </h3>
      <p className="max-w-prose text-sm text-muted-foreground">
        {t("refundHint")}
      </p>
      <form
        className="space-y-3"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        {rows.length ? (
          <ul className="space-y-2">
            {rows.map((row, index) => (
              <li
                className="flex flex-wrap items-center gap-2 text-sm"
                // The rows have no identity but their place.
                key={index}
              >
                <span>{t("refundAtLeast")}</span>
                <Input
                  aria-label={t("refundDaysLabel", { row: index + 1 })}
                  className="w-20"
                  inputMode="numeric"
                  max={MAX_DAYS}
                  min={0}
                  onChange={(event) =>
                    change(index, { days: event.target.value })
                  }
                  type="number"
                  value={row.days}
                />
                <span>{t("refundDaysBefore")}</span>
                <Input
                  aria-label={t("refundPercentLabel", { row: index + 1 })}
                  className="w-20"
                  inputMode="numeric"
                  max={100}
                  min={0}
                  onChange={(event) =>
                    change(index, { percent: event.target.value })
                  }
                  type="number"
                  value={row.percent}
                />
                <span>%</span>
                <Button
                  aria-label={t("refundRemoveRow", { row: index + 1 })}
                  onClick={() =>
                    setRows((current) =>
                      current.filter((_, at) => at !== index),
                    )
                  }
                  size="icon"
                  type="button"
                  variant="ghost"
                >
                  <Trash2Icon aria-hidden="true" />
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm">{t("refundNone")}</p>
        )}
        {deposit && rows.length ? (
          <Field>
            <label className="flex min-h-11 items-center gap-3 text-sm font-medium">
              <Switch
                checked={everything}
                onCheckedChange={(checked) => setEverything(checked)}
              />
              {t("refundCoversBalance")}
            </label>
            <FieldDescription>{t("refundCoversBalanceHint")}</FieldDescription>
          </Field>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={rows.length >= MAX_ROWS}
            onClick={() =>
              setRows((current) => [...current, { days: "", percent: "" }])
            }
            type="button"
            variant="outline"
          >
            <PlusIcon aria-hidden="true" />
            {t("refundAddRow")}
          </Button>
          <Button type="submit" variant="outline">
            {t("refundSave")}
          </Button>
        </div>
        <p
          className="text-sm text-success-foreground empty:hidden"
          role="status"
        >
          {notice}
        </p>
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
      </form>
    </section>
  );
}
