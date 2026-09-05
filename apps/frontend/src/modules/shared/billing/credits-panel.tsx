"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { CoinsIcon, ExternalLinkIcon, LoaderCircleIcon } from "lucide-react";

import {
  ApiProblemError,
  createCreditCheckout,
  getCustomerCredits,
  type CreditPack,
  type CustomerCreditsOverview,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { Link } from "#i18n/navigation";

export function CreditsPanel() {
  const t = useTranslations("Credits");
  const locale = useLocale();
  const search = useSearchParams();
  const [overview, setOverview] = useState<CustomerCreditsOverview | undefined>(
    undefined,
  );
  const [pending, setPending] = useState<string | undefined>(undefined);
  const [problem, setProblem] = useState<string | undefined>(undefined);
  // One key per pack for the whole visit: a double click must not open two
  // payments for the same intent.
  const keys = useRef<Record<string, string>>({});

  const load = useCallback(() => {
    getCustomerCredits()
      .then((value) => setOverview(value))
      .catch((error: unknown) =>
        setProblem(
          error instanceof ApiProblemError &&
            typeof error.problem.detail === "string"
            ? error.problem.detail
            : t("loadError"),
        ),
      );
  }, [t]);

  useEffect(load, [load]);

  async function buy(pack: CreditPack) {
    if (pending) return;
    setPending(pack.key);
    setProblem(undefined);
    try {
      const key = (keys.current[pack.key] ??= crypto.randomUUID());
      const session = await createCreditCheckout(pack.key, key);
      if (session.url) {
        window.location.assign(session.url);
        return;
      }
      // The simulator settles at once and hands back no address to visit.
      load();
    } catch (error) {
      setProblem(
        error instanceof ApiProblemError &&
          typeof error.problem.detail === "string"
          ? error.problem.detail
          : t("buyError"),
      );
    }
    setPending(undefined);
  }

  const balance = overview?.balance;
  const checkout = search.get("checkout");

  return (
    <div className="space-y-8">
      {checkout === "success" ? (
        <p
          className="rounded-2xl border border-primary/30 bg-primary/[0.035] px-4 py-3 text-sm"
          role="status"
        >
          {t("checkoutSuccess")}
        </p>
      ) : null}
      {checkout === "canceled" ? (
        <p
          className="rounded-2xl border px-4 py-3 text-sm text-muted-foreground"
          role="status"
        >
          {t("checkoutCanceled")}
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>
            <h2 className="flex items-center gap-2">
              <CoinsIcon aria-hidden="true" className="text-primary" />
              {t("balanceTitle")}
            </h2>
          </CardTitle>
          <CardDescription>{t("balanceDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-4xl font-semibold tracking-tight">
            {balance ? balance.available.toLocaleString(locale) : "—"}
          </p>
          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            <Figure
              label={t("fromPlan")}
              value={
                balance
                  ? t("fromPlanValue", {
                      remaining: balance.allowance_remaining,
                      granted: balance.allowance_granted,
                    })
                  : "—"
              }
              note={
                balance?.allowance_period_end
                  ? t("renewsOn", { date: balance.allowance_period_end })
                  : undefined
              }
            />
            <Figure
              label={t("purchased")}
              value={balance ? String(balance.purchased_remaining) : "—"}
              note={t("purchasedNote")}
            />
            <Figure
              label={t("reserved")}
              value={balance ? String(balance.reserved) : "—"}
              note={t("reservedNote")}
            />
          </div>
          {overview?.plan_required ? (
            <p className="mt-6 text-sm text-amber-700 dark:text-amber-500">
              {t("planRequired")}{" "}
              <Link className="underline" href="/panel/settings/billing">
                {t("planLink")}
              </Link>
            </p>
          ) : null}
        </CardContent>
      </Card>

      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}

      <section aria-labelledby="credit-packs-heading" className="space-y-4">
        <div className="max-w-3xl space-y-2">
          <h2
            className="text-2xl font-semibold tracking-tight"
            id="credit-packs-heading"
          >
            {t("packsTitle")}
          </h2>
          <p className="text-muted-foreground">{t("packsDescription")}</p>
        </div>
        <div className="grid items-stretch gap-4 lg:grid-cols-3">
          {(overview?.packs ?? []).map((pack) => (
            <Card className="rounded-2xl" key={pack.key}>
              <CardHeader>
                <CardTitle>
                  <h3>{pack.name}</h3>
                </CardTitle>
                <CardDescription>{pack.description}</CardDescription>
              </CardHeader>
              <CardContent className="flex-1">
                <p className="text-3xl font-semibold tracking-tight">
                  {pack.credits.toLocaleString(locale)}
                </p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {t("creditsFor", {
                    price: formatPrice(
                      pack.unit_amount_minor,
                      pack.currency,
                      locale,
                    ),
                  })}
                </p>
              </CardContent>
              <CardFooter>
                <Button
                  className="w-full"
                  disabled={
                    !overview?.can_buy || !pack.purchasable || Boolean(pending)
                  }
                  onClick={() => void buy(pack)}
                  variant="outline"
                >
                  {pending === pack.key ? (
                    <LoaderCircleIcon
                      aria-hidden="true"
                      className="animate-spin"
                    />
                  ) : null}
                  {!pack.purchasable
                    ? t("unavailable")
                    : !overview?.can_buy
                      ? t("ownerOnly")
                      : t("buy")}
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      </section>

      <section aria-labelledby="credit-history-heading" className="space-y-4">
        <h2
          className="text-2xl font-semibold tracking-tight"
          id="credit-history-heading"
        >
          {t("historyTitle")}
        </h2>
        {(overview?.purchases ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("historyEmpty")}</p>
        ) : (
          <ul className="divide-y rounded-2xl border">
            {(overview?.purchases ?? []).map((purchase) => (
              <li
                className="flex flex-wrap items-center gap-3 px-4 py-3"
                key={purchase.id}
              >
                <span className="text-sm font-medium">
                  {purchase.credits.toLocaleString(locale)} —{" "}
                  {formatPrice(
                    purchase.unit_amount_minor,
                    purchase.currency,
                    locale,
                  )}
                </span>
                <Badge
                  variant={
                    purchase.status === "succeeded" ? "secondary" : "outline"
                  }
                >
                  {t(`status_${purchase.status}`)}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {new Date(purchase.created_at).toLocaleDateString(locale)}
                </span>
                {purchase.status === "pending" && purchase.checkout_url ? (
                  <a
                    className="ml-auto inline-flex items-center gap-1 text-sm underline"
                    href={purchase.checkout_url}
                  >
                    {t("finishPayment")}
                    <ExternalLinkIcon aria-hidden="true" className="size-4" />
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Figure({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div>
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="text-lg font-medium">{value}</p>
      {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
    </div>
  );
}

function formatPrice(minor: number, currency: string, locale: string): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(minor / 100);
}
