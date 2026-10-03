"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";

import {
  ApiProblemError,
  type InventoryCategory,
  type InventoryItem,
  type InventoryLotStock,
  type MembershipSummary,
  type StockLocation,
  type Supplier,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";

import { PlanGate } from "#components/panel/plan-gate";
import { formatDate } from "#lib/dates";

/** The header every warehouse page shares: section, its title, last outcome. */
export type PageFrame = { eyebrow: string; notice: string; title: string };

/** What every tab of the warehouse reads; loaded once by the panel. */
export type InventoryData = {
  items: InventoryItem[];
  categories: InventoryCategory[];
  locations: StockLocation[];
  suppliers: Supplier[];
  crew: MembershipSummary[];
};

export const UNITS = [
  "piece",
  "pack",
  "ml",
  "l",
  "g",
  "kg",
  "m",
  "hour",
] as const;
export const VAT_RATES = ["23", "8", "5", "0", "zw"] as const;

/** Money in grosze and quantities with up to three decimals, in the UI locale. */
export function useFormat() {
  const locale = useLocale();
  return {
    money: (minor: number | null | undefined, currency = "PLN") =>
      minor === null || minor === undefined
        ? "—"
        : new Intl.NumberFormat(locale, { style: "currency", currency }).format(
            minor / 100,
          ),
    amount: (value: string | number) =>
      new Intl.NumberFormat(locale, { maximumFractionDigits: 3 }).format(
        Number(value),
      ),
    /** A date without a time (an expiry): read where it was written. */
    day: (iso: string) => formatDate(iso.slice(0, 10), locale),
  };
}

/** How a lot stands with its expiry: red past it, amber within 30 days. */
export function LotStatusBadge({
  status,
}: {
  status: InventoryLotStock["status"] | null | undefined;
}) {
  const t = useTranslations("Inventory");
  if (status === "expired")
    return <Badge variant="destructive">{t("lotStatus_expired")}</Badge>;
  if (status === "expiring")
    return (
      <Badge className="bg-warning text-warning-foreground">
        {t("lotStatus_expiring")}
      </Badge>
    );
  return null;
}

/** „Magazyn główny” or the person whose stock it is. */
export function locationLabel(location: StockLocation): string {
  return location.holder_name ?? location.name;
}

export function personName(person: MembershipSummary): string {
  return (
    [person.first_name, person.last_name].filter(Boolean).join(" ") ||
    person.email
  );
}

/**
 * Why the warehouse did not load (UX-079, R11): the plan leaves it out, the
 * role may not see it, or the request itself failed. Only the last one is
 * helped by „Odśwież stronę”.
 */
export type LoadProblem = "plan" | "access" | "load";

export function loadProblem(error: unknown): LoadProblem {
  if (error instanceof ApiProblemError) {
    if (error.problem.code === "entitlement_required") return "plan";
    if (error.problem.status === 403) return "access";
  }
  return "load";
}

/** Says the problem by its kind: an offer, a plain sentence, or a retry. */
export function LoadProblemNotice({
  problem,
  canManageBilling = false,
}: {
  problem: LoadProblem;
  /** Whoever may change the plan gets the way to the plans. */
  canManageBilling?: boolean;
}) {
  const t = useTranslations("Inventory");
  if (problem === "plan")
    return (
      <PlanGate
        action={
          canManageBilling
            ? {
                href: "/panel/settings/billing?feature=inventory.enabled",
                label: t("planGateAction"),
              }
            : undefined
        }
        title={t("planGateTitle")}
      >
        {t(canManageBilling ? "planGateOwner" : "planGateMember")}
      </PlanGate>
    );
  if (problem === "access")
    return <p className="text-sm text-muted-foreground">{t("accessDenied")}</p>;
  return (
    <p className="text-sm text-destructive" role="alert">
      {t("loadError")}
    </p>
  );
}

export function problemText(error: unknown, fallback: string): string {
  return error instanceof ApiProblemError ? error.message : fallback;
}

/**
 * One dialog with one form: the warehouse has many small forms and each needs
 * the same open/submit/error handling.
 */
export function FormDialog({
  open,
  onOpenChange,
  title,
  description,
  submitLabel,
  onSubmit,
  children,
  wide = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  submitLabel: string;
  /** Resolves when done; a thrown error is shown in the dialog. */
  onSubmit: () => Promise<unknown>;
  children: ReactNode;
  wide?: boolean;
}) {
  const t = useTranslations("Inventory");
  const common = useTranslations("Common");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setProblem("");
    try {
      await onSubmit();
      onOpenChange(false);
    } catch (error) {
      setProblem(problemText(error, t("failed")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next) setProblem("");
        onOpenChange(next);
      }}
      open={open}
    >
      <DialogContent
        className={wide ? "sm:max-w-3xl" : undefined}
        closeLabel={common("close")}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description ? (
            <DialogDescription>{description}</DialogDescription>
          ) : null}
        </DialogHeader>
        <form className="space-y-4" onSubmit={(event) => void submit(event)}>
          {children}
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <Button disabled={busy} type="submit">
            {submitLabel}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
