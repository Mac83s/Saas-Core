"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { updateSetupService, type ServiceSetup } from "@saas-core/api-client";
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
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { ExtrasList } from "./extras-list";
import type { PriceBook, PriceSetup } from "./price-book";
import { refusal } from "./price-dialog";
import { PriceList } from "./price-list";

/** How the customer pays, until orders bring the rest (ADR-072 §8). */
const PAYMENT_POLICIES = ["none", "on_site"] as const;

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

  async function pay(policy: (typeof PAYMENT_POLICIES)[number]) {
    setProblem(undefined);
    try {
      await updateSetupService(
        service.id,
        { payment_policy: policy, expected_version: service.version },
        crypto.randomUUID(),
      );
      setNotice(t("paymentSaved"));
    } catch (error) {
      setProblem(refusal(error, t("failed"), t("versionConflict")));
    }
    await onSetupChanged();
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
                  void pay(
                    event.target.value as (typeof PAYMENT_POLICIES)[number],
                  )
                }
                value={service.payment_policy}
              >
                {PAYMENT_POLICIES.map((policy) => (
                  <option key={policy} value={policy}>
                    {t(`payment_${policy}`)}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <FieldDescription>{t("paymentHint")}</FieldDescription>
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
