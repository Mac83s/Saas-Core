"use client";

import { useState } from "react";
import { CalendarClockIcon, XIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  cancelContentEntrySchedule,
  scheduleContentEntry,
  type ContentEntry,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

import { sitesErrorMessage } from "./problem";

/** What the browser's datetime-local field wants: local wall-clock time with
 *  no zone, which is exactly how a person thinks about "Monday at seven". */
function localInputValue(iso: string | null): string {
  if (!iso) return "";
  const moment = new Date(iso);
  const pad = (value: number) => String(value).padStart(2, "0");
  return (
    `${moment.getFullYear()}-${pad(moment.getMonth() + 1)}-${pad(moment.getDate())}` +
    `T${pad(moment.getHours())}:${pad(moment.getMinutes())}`
  );
}

/** Planning a publication, and seeing that a planned one did not happen.
 *
 *  The state matters as much as the field: an article that failed to publish on
 *  Monday morning has to look different from one nobody ever scheduled, or the
 *  operator finds out from a reader. */
export function EntrySchedule({
  entry,
  onChanged,
}: {
  entry: ContentEntry;
  onChanged: () => Promise<void>;
}) {
  const t = useTranslations("Sites");
  const [value, setValue] = useState(() =>
    localInputValue(entry.scheduled_publish_at),
  );
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  function run(action: () => Promise<unknown>) {
    setBusy(true);
    setProblem(undefined);
    void action()
      .then(() => onChanged())
      .catch((error: unknown) => {
        setProblem(sitesErrorMessage(error, t));
      })
      .finally(() => {
        setBusy(false);
      });
  }

  const pending = entry.schedule_state === "pending";
  const failed = entry.schedule_state === "failed";
  const cancelled = entry.schedule_state === "cancelled";

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <CalendarClockIcon aria-hidden="true" className="size-4" />
        <span className="font-medium">{t("scheduleTitle")}</span>
        {pending && (
          <Badge variant="secondary">{t("scheduleStatePending")}</Badge>
        )}
        {cancelled && (
          <Badge variant="outline">{t("scheduleStateCancelled")}</Badge>
        )}
        {failed && (
          <Badge variant="destructive">{t("scheduleStateFailed")}</Badge>
        )}
      </div>

      {entry.state === "published" ? (
        <p className="text-sm text-muted-foreground">
          {t("scheduleAlreadyPublished")}
        </p>
      ) : (
        <>
          <Field>
            <FieldLabel htmlFor={`schedule-${entry.id}`}>
              {t("scheduleWhen")}
            </FieldLabel>
            <Input
              disabled={busy}
              id={`schedule-${entry.id}`}
              onChange={(event) => setValue(event.target.value)}
              type="datetime-local"
              value={value}
            />
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={busy || value === ""}
              onClick={() =>
                run(() =>
                  scheduleContentEntry(entry.id, new Date(value).toISOString()),
                )
              }
              size="sm"
              type="button"
            >
              {pending ? t("scheduleMove") : t("scheduleSet")}
            </Button>
            {pending && (
              <Button
                disabled={busy}
                onClick={() => run(() => cancelContentEntrySchedule(entry.id))}
                size="sm"
                type="button"
                variant="outline"
              >
                <XIcon aria-hidden="true" />
                {t("scheduleCancel")}
              </Button>
            )}
          </div>
          <p className="text-sm text-muted-foreground">{t("scheduleHint")}</p>
        </>
      )}

      {failed && entry.schedule_error && (
        <p className="text-sm text-destructive" role="alert">
          {t("scheduleFailedReason", { reason: entry.schedule_error })}
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
