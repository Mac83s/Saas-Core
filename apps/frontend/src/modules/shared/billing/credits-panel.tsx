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
  type CreditPurchase,
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
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import {
  DemoPaymentBanner,
  Fact,
  Notice,
  SectionHeader,
  formatDay,
  formatMoney,
} from "./parts";
import { useStepUp } from "../../core/organizations/step-up";
import { deployment } from "../../../generated/deployment";

/**
 * The modules whose work costs credits. Where a product composes none of
 * them, nothing spends credits and there is nothing to top up (UX-058); what
 * each one costs is the assistant plan's „Na co wydasz kredyty” (W9).
 */
const SPENDERS = [
  "shared.image-generation",
  "shared.seo",
  "shared.translation",
];
const spendsCredits = () =>
  (deployment.modules as readonly string[]).some((module) =>
    SPENDERS.includes(module),
  );

export function CreditsPanel({
  canManageBilling = false,
}: {
  /** The owner is sent to the plan; anyone else is told to ask them. */
  canManageBilling?: boolean;
}) {
  const t = useTranslations("Credits");
  const labels = useDataTableLabels();
  const locale = useLocale();
  const search = useSearchParams();
  const [overview, setOverview] = useState<CustomerCreditsOverview | undefined>(
    undefined,
  );
  const [loadError, setLoadError] = useState<string | undefined>(undefined);
  const [pending, setPending] = useState<string | undefined>(undefined);
  const [problem, setProblem] = useState<string | undefined>(undefined);
  // A company that pays confirms a purchase with a code (52a).
  const stepUp = useStepUp();
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
      if (!stepUp.handled(error, () => buy(pack))) {
        setProblem(problemText(error, t("buyError")));
      }
    }
    setPending(undefined);
  }

  const balance = overview?.balance;
  const checkout = search.get("checkout");
  const number = (value: number) => value.toLocaleString(locale);

  const purchaseColumns: ColumnDef<CreditPurchase, unknown>[] = [
    {
      id: "credits",
      accessorKey: "credits",
      header: t("colCredits"),
      meta: { primary: true },
      cell: ({ row: { original: purchase } }) => (
        <p className="font-medium">
          {t("creditsCount", { count: purchase.credits })}
        </p>
      ),
    },
    {
      id: "date",
      accessorKey: "created_at",
      header: t("colDate"),
      cell: ({ row: { original: purchase } }) =>
        formatDay(purchase.created_at, locale),
    },
    {
      id: "amount",
      accessorKey: "unit_amount_minor",
      header: t("colAmount"),
      meta: { numeric: true },
      cell: ({ row: { original: purchase } }) =>
        formatMoney(purchase.unit_amount_minor, purchase.currency, locale),
    },
    {
      id: "status",
      accessorFn: (purchase) => t(`status_${purchase.status}`),
      header: t("colStatus"),
      cell: ({ row: { original: purchase } }) => (
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
      ),
    },
    {
      id: "actions",
      header: t("colActions"),
      meta: { actions: true },
      cell: ({ row: { original: purchase } }) =>
        purchase.status === "pending" && purchase.checkout_url ? (
          <RowActions
            items={[
              {
                label: t("finishPayment"),
                icon: <ExternalLinkIcon aria-hidden="true" />,
                inline: true,
                link: <a href={purchase.checkout_url} />,
              },
            ]}
            label={t("actionsFor", {
              date: formatDay(purchase.created_at, locale),
            })}
          />
        ) : null,
    },
  ];

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
      {stepUp.ui}
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
                      ? // The plan's credits follow the calendar month, not
                        // the day the plan is paid (UX-058).
                        t("renewsOn", {
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

          {!spendsCredits() ? (
            <p className="text-sm text-muted-foreground">
              {t("nothingSpends")}
            </p>
          ) : (
            <section
              aria-labelledby="credit-packs-heading"
              className="space-y-4"
            >
              <SectionHeader
                description={t("packsDescription")}
                id="credit-packs-heading"
                title={t("packsTitle")}
              />
              {/* Whoever cannot buy reads it once, not on three dead buttons. */}
              {!overview.can_buy && !overview.plan_required ? (
                <p className="text-sm text-muted-foreground">
                  {t("ownerBuys")}
                </p>
              ) : null}
              {overview.packs.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {t("packsEmpty")}
                </p>
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
                          {/* The price is what one compares; the credits are
                            in the pack's name already (UX-058). */}
                          <p className="text-3xl font-semibold tracking-tight tabular-nums">
                            {formatMoney(
                              pack.unit_amount_minor,
                              pack.currency,
                              locale,
                            )}
                          </p>
                          <p className="mt-1 text-sm text-muted-foreground">
                            {t("packContents", { count: pack.credits })}
                          </p>
                        </CardContent>
                        {!overview.can_buy && !overview.plan_required ? null : (
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
                                ? // A dead button says why (UX-058).
                                  t(
                                    overview.payment_mode === "simulated"
                                      ? "unavailableDemo"
                                      : "unavailable",
                                  )
                                : overview.plan_required
                                  ? t("needsPlan")
                                  : t("buy")}
                            </Button>
                          </CardFooter>
                        )}
                      </Card>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          <section
            aria-labelledby="credit-history-heading"
            className="space-y-4"
          >
            <SectionHeader
              id="credit-history-heading"
              title={t("historyTitle")}
            />
            <DataTable
              caption={t("historyTitle")}
              columns={purchaseColumns}
              data={overview.purchases}
              getRowId={(purchase) => purchase.id}
              labels={{ ...labels, empty: t("historyEmpty") }}
            />
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
