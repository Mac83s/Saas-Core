"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import {
  ApiProblemError,
  anonymizeCustomer,
  previewCustomerAnonymization,
  type CustomerKept,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";

import { formatDate } from "#lib/dates";

function refusal(error: unknown, fallback: string): string {
  if (!(error instanceof ApiProblemError)) return fallback;
  return error.problem.errors?.[0]?.message ?? fallback;
}

/**
 * The question before a customer's data is removed by hand (ADR-073, slice
 * 4i) — the same wherever the panel offers it: what goes, what stays, and
 * what a module must still keep and until which day, read from the server
 * before anybody confirms. Nothing about a period is worked out here.
 */
export function RemoveCustomerDialog({
  customerId,
  name,
  onDone,
  onOpenChange,
}: {
  customerId: string;
  /** The customer as the screen that opened the window names them. */
  name: string;
  onDone: () => void;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("CustomerRemoval");
  const common = useTranslations("Common");
  const locale = useLocale();
  const [kept, setKept] = useState<CustomerKept[]>();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  useEffect(() => {
    let active = true;
    previewCustomerAnonymization(customerId).then(
      (preview) => {
        if (active) setKept(preview.kept);
      },
      (error: unknown) => {
        if (active) setProblem(refusal(error, t("previewFailed")));
      },
    );
    return () => {
      active = false;
    };
  }, [customerId, t]);

  async function confirm() {
    setBusy(true);
    setProblem(undefined);
    try {
      await anonymizeCustomer(customerId);
      onDone();
    } catch (error) {
      setProblem(refusal(error, t("failed")));
    } finally {
      setBusy(false);
    }
  }

  // One reason for every order it holds for: said once, under the list.
  const reasons = [
    ...new Set(
      (kept ?? []).map((item) => (locale === "en" ? item.why.en : item.why.pl)),
    ),
  ].filter(Boolean);

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent closeLabel={common("close")}>
        <DialogHeader>
          <DialogTitle>{t("title", { name })}</DialogTitle>
          <DialogDescription>{t("goes")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <p>{t("stays")}</p>
          {kept === undefined && !problem ? (
            <p className="text-muted-foreground" role="status">
              {t("checking")}
            </p>
          ) : null}
          {kept?.length ? (
            <section aria-labelledby="anonymize-kept" className="space-y-1.5">
              <h3 className="font-medium" id="anonymize-kept">
                {t("keptTitle")}
              </h3>
              <ul className="list-disc space-y-1 pl-5">
                {kept.map((item) => (
                  <li key={`${item.kind}-${item.reference}`}>
                    {t("keptOrder", {
                      number: item.label,
                      until: formatDate(item.until, locale),
                    })}
                  </li>
                ))}
              </ul>
              {reasons.map((reason) => (
                <p className="text-muted-foreground" key={reason}>
                  {reason}
                </p>
              ))}
            </section>
          ) : null}
          {kept?.length === 0 ? <p>{t("keptNothing")}</p> : null}
        </div>
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
        <DialogFooter>
          <DialogClose render={<Button type="button" variant="outline" />}>
            {common("cancel")}
          </DialogClose>
          <Button
            disabled={busy || kept === undefined}
            onClick={() => void confirm()}
            type="button"
            variant="destructive"
          >
            {t("confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
