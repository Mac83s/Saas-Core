"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiProblemError,
  updateSetupService,
  type ServiceSetup,
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
import {
  Field,
  FieldDescription,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { Link } from "#i18n/navigation";

import { ExtrasList } from "./extras-list";
import type { PriceBook, PriceSetup } from "./price-book";
import { refusal } from "./price-dialog";
import { PriceList } from "./price-list";
import { RefundTerms } from "./refund-terms";

/** How the customer pays (ADR-072 §8). The last three ask for money before
 *  the booking is confirmed: it waits for the transfer (ADR-073 §5). */
const PAYMENT_POLICIES = [
  "none",
  "on_site",
  "transfer",
  "deposit",
  "full",
] as const;
type PaymentPolicy = (typeof PAYMENT_POLICIES)[number];
const AHEAD: readonly PaymentPolicy[] = ["transfer", "deposit", "full"];
/** The server's refusals the panel says in its own language. */
const PAYMENT_REFUSALS = ["transfer_account_missing", "orders_required"];

/**
 * „Cennik” of one offer (phase 3e): its prices with the question which of
 * them applies on a day, its extras and deposit, and how the customer pays.
 * Each of them saves on its own; the dialog only closes.
 */
export function OfferPricesDialog({
  book,
  finalFocus,
  onChanged,
  onOpenChange,
  onSetupChanged,
  service,
  setup,
  zone,
}: {
  book: PriceBook;
  finalFocus: HTMLElement | null;
  onChanged: () => Promise<void> | void;
  onOpenChange: (open: boolean) => void;
  /** The offer itself changed (how the customer pays): the setup is read again. */
  onSetupChanged: () => Promise<void> | void;
  service: ServiceSetup;
  setup: PriceSetup;
  zone: string;
}) {
  const t = useTranslations("PriceList");
  const common = useTranslations("Common");
  const [problem, setProblem] = useState<string>();
  const [notice, setNotice] = useState("");
  // What the select shows: a prepayment is saved with its percent, by the
  // button, so until then the choice lives here.
  const [policy, setPolicy] = useState<PaymentPolicy>(
    service.payment_policy as PaymentPolicy,
  );
  const [percent, setPercent] = useState(String(service.deposit_percent ?? 30));
  const [days, setDays] = useState(String(service.transfer_due_days ?? 3));
  // The rest of a prepaid price: on site, or by a transfer some days before
  // the start (ADR-073 §5).
  const [balanceAhead, setBalanceAhead] = useState(
    service.balance_due_days_before != null,
  );
  const [balanceDays, setBalanceDays] = useState(
    String(service.balance_due_days_before ?? 14),
  );
  const ahead = AHEAD.includes(policy);

  async function pay(next: PaymentPolicy, terms = false) {
    setProblem(undefined);
    setNotice("");
    const share = Number(percent);
    const due = Number(days);
    if (terms && next === "deposit" && !(share >= 1 && share <= 99))
      return setProblem(t("depositPercentInvalid"));
    if (terms && !(due >= 1 && due <= 30))
      return setProblem(t("transferDaysInvalid"));
    const before = Number(balanceDays);
    if (
      terms &&
      next === "deposit" &&
      balanceAhead &&
      !(
        balanceDays.trim() !== "" &&
        Number.isInteger(before) &&
        before >= 0 &&
        before <= 365
      )
    )
      return setProblem(t("balanceDaysInvalid"));
    try {
      await updateSetupService(
        service.id,
        {
          payment_policy: next,
          ...(terms
            ? {
                transfer_due_days: due,
                ...(next === "deposit"
                  ? {
                      deposit_percent: share,
                      balance_due_days_before: balanceAhead ? before : null,
                    }
                  : {}),
              }
            : {}),
          expected_version: service.version,
        },
        crypto.randomUUID(),
      );
      setNotice(t("paymentSaved"));
    } catch (error) {
      const code =
        error instanceof ApiProblemError
          ? error.problem.errors?.[0]?.code
          : undefined;
      setProblem(
        code && PAYMENT_REFUSALS.includes(code)
          ? t(`paymentRefused_${code}`)
          : refusal(error, t("failed"), t("versionConflict")),
      );
      // The offer keeps what it had.
      if (!terms) setPolicy(service.payment_policy as PaymentPolicy);
    }
    await onSetupChanged();
  }

  function choose(next: PaymentPolicy) {
    setPolicy(next);
    setProblem(undefined);
    setNotice("");
    // A prepayment waits for its percent; everything else saves at once.
    if (next !== "deposit") void pay(next);
  }

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-3xl"
        closeLabel={common("close")}
        finalFocus={() => finalFocus ?? true}
      >
        <DialogHeader>
          <DialogTitle>{t("titleFor", { name: service.name })}</DialogTitle>
          <DialogDescription>{t("offerHint")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-8">
          <PriceList
            book={book}
            description={t("pricesHint")}
            onChanged={onChanged}
            service={service}
            setup={setup}
            title={t("pricesTitle")}
            zone={zone}
          />
          <ExtrasList
            amounts={book.amounts}
            extras={book.extras}
            onChanged={onChanged}
            services={[service]}
          />
          <Field>
            <FieldLabel htmlFor="offer-payment">{t("payment")}</FieldLabel>
            {/* The width is the box's: the select's arrow stays inside it. */}
            <div className="sm:max-w-sm">
              <NativeSelect
                id="offer-payment"
                onChange={(event) =>
                  choose(event.target.value as PaymentPolicy)
                }
                value={policy}
              >
                {PAYMENT_POLICIES.map((value) => (
                  <option key={value} value={value}>
                    {t(`payment_${value}`)}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <FieldDescription>{t("paymentHint")}</FieldDescription>
            {ahead ? (
              <form
                className="space-y-3 rounded-lg border p-4"
                noValidate
                onSubmit={(event) => {
                  event.preventDefault();
                  void pay(policy, true);
                }}
              >
                <p className="text-sm">
                  {t.rich("paymentAheadHint", {
                    settings: (chunks) => (
                      <Link
                        className="font-medium text-primary hover:underline"
                        href="/panel/settings/customer-payments"
                      >
                        {chunks}
                      </Link>
                    ),
                  })}
                </p>
                <div className="flex flex-wrap items-end gap-4">
                  {policy === "deposit" ? (
                    <Field className="w-36">
                      <FieldLabel htmlFor="offer-deposit-percent">
                        {t("depositPercent")}
                      </FieldLabel>
                      <Input
                        id="offer-deposit-percent"
                        inputMode="numeric"
                        max={99}
                        min={1}
                        onChange={(event) => setPercent(event.target.value)}
                        type="number"
                        value={percent}
                      />
                    </Field>
                  ) : null}
                  <Field className="w-36">
                    <FieldLabel htmlFor="offer-transfer-days">
                      {t("transferDays")}
                    </FieldLabel>
                    <Input
                      id="offer-transfer-days"
                      inputMode="numeric"
                      max={30}
                      min={1}
                      onChange={(event) => setDays(event.target.value)}
                      type="number"
                      value={days}
                    />
                  </Field>
                  {policy === "deposit" ? (
                    <Field className="w-72">
                      <FieldLabel htmlFor="offer-balance">
                        {t("balance")}
                      </FieldLabel>
                      <NativeSelect
                        id="offer-balance"
                        onChange={(event) =>
                          setBalanceAhead(event.target.value === "transfer")
                        }
                        value={balanceAhead ? "transfer" : "on_site"}
                      >
                        <option value="on_site">{t("balance_on_site")}</option>
                        <option value="transfer">
                          {t("balance_transfer")}
                        </option>
                      </NativeSelect>
                    </Field>
                  ) : null}
                  {policy === "deposit" && balanceAhead ? (
                    <Field className="w-44">
                      <FieldLabel htmlFor="offer-balance-days">
                        {t("balanceDays")}
                      </FieldLabel>
                      <Input
                        id="offer-balance-days"
                        inputMode="numeric"
                        max={365}
                        min={0}
                        onChange={(event) => setBalanceDays(event.target.value)}
                        type="number"
                        value={balanceDays}
                      />
                    </Field>
                  ) : null}
                  <Button type="submit" variant="outline">
                    {t("paymentTermsSave")}
                  </Button>
                </div>
                {policy === "deposit" && balanceAhead ? (
                  <p className="text-sm text-muted-foreground">
                    {t("balanceHint")}
                  </p>
                ) : null}
              </form>
            ) : null}
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
          </Field>
          {/* Refund thresholds matter where money comes before the visit. */}
          {ahead || (service.cancellation_refunds ?? []).length ? (
            <RefundTerms
              deposit={policy === "deposit"}
              onSetupChanged={onSetupChanged}
              service={service}
            />
          ) : null}
        </div>
        <DialogFooter>
          <DialogClose render={<Button type="button" variant="outline" />}>
            {common("close")}
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
