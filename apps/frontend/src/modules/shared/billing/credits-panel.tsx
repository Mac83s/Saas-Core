"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import {
  CheckIcon,
  CircleAlertIcon,
  CoinsIcon,
  ExternalLinkIcon,
  LoaderCircleIcon,
  LockKeyholeIcon,
  RefreshCwIcon,
} from "lucide-react";

import {
  ApiProblemError,
  createCreditCheckout,
  getCustomerCredits,
  type CreditPack,
  type CustomerCreditsOverview,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { Link } from "#i18n/navigation";
import {
  DemoPaymentBanner,
  Fact,
  Notice,
  SectionHeader,
  formatDay,
  formatMoney,
} from "./parts";

export function CreditsPanel({
  canManageBilling = false,
}: {
  /** The owner is sent to the plan; anyone else is told to ask them. */
  canManageBilling?: boolean;
}) {
  const t = useTranslations("Credits");
  const locale = useLocale();
  const search = useSearchParams();
  const [overview, setOverview] = useState<CustomerCreditsOverview | undefined>(
    undefined,
  );
  const [loadError, setLoadError] = useState<string | undefined>(undefined);
  const [pending, setPending] = useState<string | undefined>(undefined);
  const [problem, setProblem] = useState<string | undefined>(undefined);
  // One key per pack for the whole visit: a double click must not open two
  // payments for the same intent.
  const keys = useRef<Record<string, string>>({});

  const load = useCallback(() => {
    getCustomerCredits()
      .then((value) => setOverview(value))
      .catch((error: unknown) =>
        setLoadError(problemText(error, t("loadError"))),
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
      setProblem(problemText(error, t("buyError")));
    }
    setPending(undefined);
  }

  const balance = overview?.balance;
  const checkout = search.get("checkout");
  const number = (value: number) => value.toLocaleString(locale);

  return (
    <div className="space-y-8">
      {overview?.payment_mode === "simulated" ? <DemoPaymentBanner /> : null}
      {checkout === "success" ? (
        <Notice
          icon={CheckIcon}
          role="status"
          title={t("checkoutSuccess")}
          tone="success"
        />
      ) : null}
      {checkout === "canceled" ? (
        <Notice
          icon={CircleAlertIcon}
          role="status"
          title={t("checkoutCanceled")}
          tone="warning"
        />
      ) : null}
      {problem ? (
        <Notice
          icon={CircleAlertIcon}
          role="alert"
          title={problem}
          tone="destructive"
        />
      ) : null}
      {loadError ? (
        <Notice
          action={
            <Button
              onClick={() => {
                setLoadError(undefined);
                load();
              }}
              type="button"
              variant="outline"
            >
              <RefreshCwIcon aria-hidden="true" />
              {t("retry")}
            </Button>
          }
          icon={CircleAlertIcon}
          role="alert"
          title={loadError}
          tone="destructive"
        />
      ) : null}

      {!overview && !loadError ? (
        <div aria-busy="true" aria-label={t("loading")} className="space-y-4">
          <div className="h-52 animate-pulse rounded-xl bg-muted" />
          <div className="grid gap-4 lg:grid-cols-3">
            {[0, 1, 2].map((item) => (
              <div
                className="h-56 animate-pulse rounded-xl bg-muted"
                key={item}
              />
            ))}
          </div>
        </div>
      ) : null}

      {overview && balance ? (
        <>
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
            <CardContent className="space-y-5">
              <p className="text-4xl font-semibold tracking-tight tabular-nums">
                {number(balance.available)}
              </p>
              <dl className="grid gap-3 sm:grid-cols-3">
                <Fact
                  label={t("fromPlan")}
                  note={
                    balance.allowance_period_end
                      ? t("renewsOn", {
                          date: formatDay(balance.allowance_period_end, locale),
                        })
                      : undefined
                  }
                  share={
                    balance.allowance_granted > 0
                      ? balance.allowance_remaining / balance.allowance_granted
                      : undefined
                  }
                  value={t("fromPlanValue", {
                    remaining: balance.allowance_remaining,
                    granted: balance.allowance_granted,
                  })}
                />
                <Fact
                  label={t("purchased")}
                  note={t("purchasedNote")}
                  value={number(balance.purchased_remaining)}
                />
                <Fact
                  label={t("reserved")}
                  note={t("reservedNote")}
                  value={number(balance.reserved)}
                />
              </dl>
              {overview.plan_required ? (
                <Notice
                  action={
                    canManageBilling ? (
                      <Link
                        className={buttonVariants({ variant: "outline" })}
                        href="/panel/settings/billing"
                      >
                        {t("planLink")}
                      </Link>
                    ) : null
                  }
                  icon={LockKeyholeIcon}
                  title={t("planRequired")}
                  tone="warning"
                >
                  {canManageBilling ? null : t("askOwner")}
                </Notice>
              ) : null}
            </CardContent>
          </Card>

          <section aria-labelledby="credit-packs-heading" className="space-y-4">
            <SectionHeader
              description={t("packsDescription")}
              id="credit-packs-heading"
              title={t("packsTitle")}
            />
            {overview.packs.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("packsEmpty")}</p>
            ) : (
              <ul className="grid items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {overview.packs.map((pack) => (
                  <li className="flex" key={pack.key}>
                    <Card className="w-full">
                      <CardHeader>
                        <CardTitle className="text-lg font-semibold">
                          <h3>{pack.name}</h3>
                        </CardTitle>
                        <CardDescription>{pack.description}</CardDescription>
                      </CardHeader>
                      <CardContent className="flex-1">
                        <p className="text-3xl font-semibold tracking-tight tabular-nums">
                          {number(pack.credits)}
                        </p>
                        <p className="mt-1 text-sm text-muted-foreground">
                          {t("creditsFor", {
                            price: formatMoney(
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
                            !overview.can_buy ||
                            !pack.purchasable ||
                            Boolean(pending)
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
                            : overview.plan_required
                              ? t("needsPlan")
                              : !overview.can_buy
                                ? t("ownerOnly")
                                : t("buy")}
                        </Button>
                      </CardFooter>
                    </Card>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section
            aria-labelledby="credit-history-heading"
            className="space-y-4"
          >
            <SectionHeader
              id="credit-history-heading"
              title={t("historyTitle")}
            />
            {overview.purchases.length === 0 ? (
              <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
                {t("historyEmpty")}
              </p>
            ) : (
              <ul className="divide-y rounded-lg border">
                {overview.purchases.map((purchase) => (
                  <li
                    className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3"
                    key={purchase.id}
                  >
                    <div className="min-w-0 flex-1 basis-40">
                      <p className="font-medium">
                        {t("creditsCount", { count: purchase.credits })}
                      </p>
                      <p className="text-sm text-muted-foreground">
                        {formatDay(purchase.created_at, locale)} ·{" "}
                        {formatMoney(
                          purchase.unit_amount_minor,
                          purchase.currency,
                          locale,
                        )}
                      </p>
                    </div>
                    <Badge
                      variant={
                        purchase.status === "succeeded"
                          ? "secondary"
                          : purchase.status === "failed"
                            ? "destructive"
                            : "outline"
                      }
                    >
                      {t(`status_${purchase.status}`)}
                    </Badge>
                    {purchase.status === "pending" && purchase.checkout_url ? (
                      <a
                        className={buttonVariants({ variant: "outline" })}
                        href={purchase.checkout_url}
                      >
                        {t("finishPayment")}
                        <ExternalLinkIcon aria-hidden="true" />
                      </a>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}

function problemText(error: unknown, fallback: string): string {
  return error instanceof ApiProblemError &&
    typeof error.problem.detail === "string"
    ? error.problem.detail
    : fallback;
}
