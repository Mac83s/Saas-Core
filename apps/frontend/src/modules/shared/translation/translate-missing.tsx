"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { LanguagesIcon } from "lucide-react";

import {
  getTranslationOffer,
  orderTranslation,
  quoteTranslation,
  type TranslationQuote,
  type TranslationTarget,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";

type Offer = "absent" | "unavailable" | "available";

/**
 * „Przetłumacz brakujące” (TL12d): quote what is missing or out of date in
 * these languages, say what it costs, order it on the person's click. Hidden
 * where the deployment has no translation engine; one line instead while the
 * platform has not switched it on yet (no model or price).
 */
export function TranslateMissing({
  targets,
  disabled = false,
  onOrdered,
}: {
  targets: TranslationTarget[];
  disabled?: boolean;
  onOrdered?: () => void;
}) {
  const t = useTranslations("Translations");
  const [offer, setOffer] = useState<Offer>();
  const [quote, setQuote] = useState<TranslationQuote>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let alive = true;
    getTranslationOffer()
      .then((answer) => {
        if (alive) setOffer(answer.available ? "available" : "unavailable");
      })
      .catch(() => {
        if (alive) setOffer("absent");
      });
    return () => {
      alive = false;
    };
  }, []);

  if (offer === undefined || offer === "absent" || targets.length === 0)
    return null;
  if (offer === "unavailable")
    return (
      <p className="text-sm text-muted-foreground">{t("automaticSoon")}</p>
    );

  async function ask() {
    setBusy(true);
    setMessage("");
    try {
      const answer = await quoteTranslation(targets);
      if (answer.units === 0) setMessage(t("nothingMissing"));
      else setQuote(answer);
    } catch {
      setMessage(t("quoteFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function order(current: TranslationQuote) {
    setBusy(true);
    try {
      await orderTranslation(targets, current, crypto.randomUUID());
      setQuote(undefined);
      setMessage(t("ordered"));
      onOrdered?.();
    } catch {
      setMessage(t("orderFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <Button
        disabled={disabled || busy}
        onClick={() => void ask()}
        variant="outline"
      >
        <LanguagesIcon aria-hidden="true" />
        {t("translateMissing")}
      </Button>
      <p className="text-sm text-muted-foreground empty:hidden" role="status">
        {message}
      </p>
      <Dialog
        onOpenChange={(open) => (open ? null : setQuote(undefined))}
        open={quote !== undefined}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("confirmTitle")}</DialogTitle>
            <DialogDescription>
              {quote ? t("confirmCost", { credits: quote.credits }) : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              disabled={busy}
              onClick={() => setQuote(undefined)}
              variant="outline"
            >
              {t("cancel")}
            </Button>
            <Button
              disabled={busy || !quote}
              onClick={() => quote && void order(quote)}
            >
              {t("confirmOrder")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
