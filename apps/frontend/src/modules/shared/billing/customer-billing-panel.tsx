"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import {
  CheckIcon,
  CircleAlertIcon,
  CreditCardIcon,
  ExternalLinkIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
  SparklesIcon,
} from "lucide-react";

import {
  ApiProblemError,
  activateBillingTrial,
  createBillingCheckout,
  createBillingPortal,
  getCustomerBillingOverview,
  type CustomerBillingOverview,
  type CustomerPlan,
} from "@saas-core/api-client";
import { BillingDetailsForm } from "./billing-details-form";
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
import { cn } from "@saas-core/ui/lib/utils";

export function CustomerBillingPanel() {
  const t = useTranslations("CustomerBilling");
  const locale = useLocale();
  const searchParams = useSearchParams();
  const checkoutState = searchParams.get("checkout");
  const checkoutSessionId = searchParams.get("session_id");
  const checkoutKeys = useRef<Record<string, string>>({});
  const activationResultRef = useRef<HTMLDivElement>(null);
  const [overview, setOverview] = useState<CustomerBillingOverview>();
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const [problemRetry, setProblemRetry] = useState<"load" | "activation">();
  const [activated, setActivated] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setProblem(undefined);
    setProblemRetry(undefined);
    try {
      setOverview(await getCustomerBillingOverview());
    } catch (error) {
      setProblem(errorMessage(error, t));
      setProblemRetry("load");
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    let mounted = true;
    void getCustomerBillingOverview()
      .then((data) => {
        if (mounted) setOverview(data);
      })
      .catch((error: unknown) => {
        if (mounted) {
          setProblem(errorMessage(error, t));
          setProblemRetry("load");
        }
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [t]);

  useEffect(() => {
    if (activated) activationResultRef.current?.focus();
  }, [activated]);

  async function choosePlan(plan: CustomerPlan) {
    if (
      plan.is_current ||
      pending ||
      (overview?.payment_mode === "simulated" &&
        overview.has_active_subscription)
    )
      return;
    setPending(plan.key);
    setProblem(undefined);
    setProblemRetry(undefined);
    try {
      if (
        overview?.payment_mode === "stripe" &&
        overview.has_active_subscription &&
        overview.portal_available
      ) {
        const session = await createBillingPortal();
        window.location.assign(session.url);
        return;
      }
      const key = (checkoutKeys.current[plan.key] ??= crypto.randomUUID());
      const session = await createBillingCheckout(plan.key, key);
      window.location.assign(session.url);
    } catch (error) {
      setProblem(errorMessage(error, t, overview?.payment_mode));
      setProblemRetry(undefined);
      setPending(undefined);
    }
  }

  async function openPortal() {
    if (pending || overview?.payment_mode !== "stripe") return;
    setPending("portal");
    setProblem(undefined);
    setProblemRetry(undefined);
    try {
      const session = await createBillingPortal();
      window.location.assign(session.url);
    } catch (error) {
      setProblem(errorMessage(error, t, overview?.payment_mode));
      setProblemRetry(undefined);
      setPending(undefined);
    }
  }

  async function activateTrial() {
    if (!checkoutSessionId || pending) return;
    setPending("activation");
    setProblem(undefined);
    setProblemRetry(undefined);
    try {
      for (let attempt = 0; ; attempt += 1) {
        try {
          await activateBillingTrial(checkoutSessionId);
          break;
        } catch (error) {
          if (
            !isProblemCode(error, "completed_checkout_required") ||
            attempt >= 3
          ) {
            throw error;
          }
          await wait(750 * 2 ** attempt);
        }
      }
      await load();
      setActivated(true);
    } catch (error) {
      setProblem(errorMessage(error, t, overview?.payment_mode));
      setProblemRetry(
        isProblemCode(error, "completed_checkout_required")
          ? "activation"
          : undefined,
      );
    } finally {
      setPending(undefined);
    }
  }

  const subscription = overview?.subscription;
  const isSimulated = overview?.payment_mode === "simulated";

  return (
    <div className="space-y-8">
      {isSimulated ? (
        <aside
          aria-label={t("simulationBannerTitle")}
          className="flex items-start gap-3 rounded-2xl border border-info-foreground/30 bg-info p-4 text-sm"
        >
          <SparklesIcon
            aria-hidden="true"
            className="mt-0.5 size-5 shrink-0 text-info-foreground"
          />
          <div>
            <p className="font-medium">{t("simulationBannerTitle")}</p>
            <p className="mt-1 text-muted-foreground">
              {t("simulationBannerDescription")}
            </p>
          </div>
        </aside>
      ) : null}

      {/* The same question as the plan buttons ask: a canceled plan still has a
          payload, and reading its presence as "already subscribed" is what
          silently skipped the activation after a real payment. */}
      {checkoutState === "success" &&
      overview &&
      !overview.has_active_subscription &&
      !activated ? (
        <Card className="border-primary/30 bg-primary/[0.035]">
          <CardHeader>
            <CardTitle>
              <h2 className="flex items-center gap-2">
                <SparklesIcon aria-hidden="true" className="text-primary" />
                {t(
                  isSimulated
                    ? "simulatedCheckoutSuccessTitle"
                    : "checkoutSuccessTitle",
                )}
              </h2>
            </CardTitle>
            <CardDescription>
              {t(
                isSimulated
                  ? "simulatedCheckoutSuccessDescription"
                  : "checkoutSuccessDescription",
              )}
            </CardDescription>
          </CardHeader>
          <CardFooter className="justify-end">
            <Button
              disabled={!checkoutSessionId || Boolean(pending)}
              onClick={() => void activateTrial()}
              size="lg"
            >
              {pending === "activation" ? (
                <LoaderCircleIcon aria-hidden="true" className="animate-spin" />
              ) : (
                <SparklesIcon aria-hidden="true" />
              )}
              {t("activateTrial")}
            </Button>
          </CardFooter>
        </Card>
      ) : null}

      {activated ? (
        <div
          aria-live="polite"
          className="flex items-start gap-3 rounded-2xl border border-success-foreground/30 bg-success p-4 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          ref={activationResultRef}
          role="status"
          tabIndex={-1}
        >
          <CheckIcon
            aria-hidden="true"
            className="mt-0.5 size-5 shrink-0 text-success-foreground"
          />
          <div>
            <p className="font-medium">{t("trialActivatedTitle")}</p>
            <p className="mt-1 text-muted-foreground">
              {t("trialActivatedDescription")}
            </p>
          </div>
        </div>
      ) : null}

      {checkoutState === "canceled" && overview ? (
        <div
          className="flex items-start gap-3 rounded-2xl border border-warning-foreground/30 bg-warning p-4 text-sm"
          role="status"
        >
          <CircleAlertIcon
            aria-hidden="true"
            className="mt-0.5 size-5 text-warning-foreground"
          />
          <div>
            <p className="font-medium">
              {t(
                isSimulated
                  ? "simulatedCheckoutCanceledTitle"
                  : "checkoutCanceledTitle",
              )}
            </p>
            <p className="mt-1 text-muted-foreground">
              {t(
                isSimulated
                  ? "simulatedCheckoutCanceledDescription"
                  : "checkoutCanceledDescription",
              )}
            </p>
          </div>
        </div>
      ) : null}

      {problem ? (
        <div
          className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          role="alert"
        >
          <span>{problem}</span>
          {problemRetry ? (
            <Button
              disabled={loading || Boolean(pending)}
              onClick={() =>
                void (problemRetry === "activation" ? activateTrial() : load())
              }
              size="sm"
              type="button"
              variant="outline"
            >
              <RefreshCwIcon
                aria-hidden="true"
                className={loading || pending ? "animate-spin" : ""}
              />
              {t(problemRetry === "activation" ? "retryActivation" : "retry")}
            </Button>
          ) : null}
        </div>
      ) : null}

      {loading && !overview ? (
        <div aria-label={t("loading")} className="space-y-4">
          <div className="h-48 animate-pulse rounded-2xl bg-muted" />
          <div className="grid gap-4 lg:grid-cols-3">
            {[0, 1, 2].map((item) => (
              <div
                className="h-96 animate-pulse rounded-2xl bg-muted"
                key={item}
              />
            ))}
          </div>
        </div>
      ) : null}

      {overview ? (
        <section aria-labelledby="current-plan-heading">
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="space-y-1">
                  <CardTitle>
                    <h2 id="current-plan-heading">{t("currentPlan")}</h2>
                  </CardTitle>
                  <CardDescription>
                    {subscription
                      ? t("currentPlanDescription", {
                          plan: planLabel(subscription.plan_key, t),
                          state: stateLabel(subscription.state, t, isSimulated),
                        })
                      : t("noPlanDescription")}
                  </CardDescription>
                </div>
                {subscription ? (
                  <Badge
                    variant={
                      subscription.access_mode === "full"
                        ? "default"
                        : "outline"
                    }
                  >
                    {stateLabel(subscription.state, t, isSimulated)}
                  </Badge>
                ) : (
                  <Badge variant="outline">{t("noPlan")}</Badge>
                )}
              </div>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-3">
              <StatusValue
                label={t("planLabel")}
                value={subscription ? planLabel(subscription.plan_key, t) : "—"}
              />
              <StatusValue
                label={t("trialEnds")}
                value={formatDate(subscription?.trial_end, locale)}
              />
              <StatusValue
                label={t("periodEnds")}
                value={formatDate(subscription?.current_period_end, locale)}
              />
            </CardContent>
            {subscription?.cancel_at_period_end ? (
              <CardContent className="pt-0">
                <div className="rounded-xl border border-warning-foreground/30 bg-warning p-4 text-sm">
                  {t("cancellationScheduled", {
                    date: formatDate(subscription.current_period_end, locale),
                  })}
                </div>
              </CardContent>
            ) : null}
            {subscription && subscription.access_mode !== "full" ? (
              <CardContent className="pt-0">
                <div className="rounded-xl border border-warning-foreground/30 bg-warning p-4 text-sm">
                  {accessModeLabel(subscription.access_mode, t, isSimulated)}
                </div>
              </CardContent>
            ) : null}
            {subscription?.grace_period_end ? (
              <CardContent className="pt-0">
                <div className="rounded-xl border border-warning-foreground/30 bg-warning p-4 text-sm">
                  {t(isSimulated ? "simulatedGraceEnds" : "graceEnds", {
                    date: formatDate(subscription.grace_period_end, locale),
                  })}
                </div>
              </CardContent>
            ) : null}
            {overview.payment_mode === "stripe" &&
            overview.portal_available &&
            overview.can_manage ? (
              <CardFooter className="justify-end">
                <Button
                  disabled={Boolean(pending)}
                  onClick={() => void openPortal()}
                  variant="outline"
                >
                  {pending === "portal" ? (
                    <LoaderCircleIcon
                      aria-hidden="true"
                      className="animate-spin"
                    />
                  ) : (
                    <CreditCardIcon aria-hidden="true" />
                  )}
                  {t("managePayment")}
                  <ExternalLinkIcon aria-hidden="true" />
                </Button>
              </CardFooter>
            ) : null}
          </Card>
        </section>
      ) : null}

      {overview ? (
        <BillingDetailsForm
          canManage={overview.can_manage}
          details={overview.billing_details}
          onSaved={(billing_details) =>
            setOverview({ ...overview, billing_details })
          }
        />
      ) : null}

      {overview ? (
        <section aria-labelledby="plans-heading" className="space-y-4">
          <div className="max-w-3xl space-y-2">
            <h2
              className="text-2xl font-semibold tracking-tight"
              id="plans-heading"
            >
              {t("plansTitle")}
            </h2>
            <p className="text-muted-foreground">{t("plansDescription")}</p>
          </div>
          <div className="grid items-stretch gap-4 lg:grid-cols-3">
            {overview.plans.map((plan) => (
              <PlanCard
                busy={Boolean(pending)}
                canManage={overview.can_manage}
                detailsComplete={overview.billing_details.missing.length === 0}
                hasSubscription={overview.has_active_subscription}
                highlighted={plan.key === "starter"}
                key={`${plan.key}:${plan.version}`}
                locale={locale}
                onChoose={() => void choosePlan(plan)}
                pending={pending === plan.key}
                plan={plan}
                paymentMode={overview.payment_mode}
              />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function PlanCard({
  plan,
  locale,
  highlighted,
  pending,
  busy,
  canManage,
  detailsComplete,
  hasSubscription,
  paymentMode,
  onChoose,
}: {
  plan: CustomerPlan;
  locale: string;
  highlighted: boolean;
  pending: boolean;
  busy: boolean;
  canManage: boolean;
  detailsComplete: boolean;
  hasSubscription: boolean;
  paymentMode: CustomerBillingOverview["payment_mode"];
  onChoose: () => void;
}) {
  const t = useTranslations("CustomerBilling");
  const benefits = planBenefits(plan, t, locale);
  const simulatedPlanLocked =
    paymentMode === "simulated" && hasSubscription && !plan.is_current;
  return (
    <Card
      className={cn(
        "relative rounded-2xl",
        highlighted && "border-primary/40 ring-2 ring-primary/20",
      )}
    >
      {highlighted ? (
        <Badge className="absolute right-4 top-4" variant="default">
          {t("recommended")}
        </Badge>
      ) : null}
      <CardHeader className="pr-28">
        <CardTitle className="text-xl">
          <h3>{planLabel(plan.key, t)}</h3>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-6">
        <div>
          <span className="text-3xl font-semibold tracking-tight">
            {formatPrice(plan.unit_amount_minor, plan.currency, locale)}
          </span>
          <span className="text-sm text-muted-foreground">
            {" "}
            {t(plan.billing_interval === "year" ? "perYearNet" : "perMonthNet")}
          </span>
          {plan.trial_days > 0 ? (
            <p className="mt-2 text-sm font-medium text-primary">
              {t("trialDays", { count: plan.trial_days })}
            </p>
          ) : null}
        </div>
        <p className="min-h-12 text-sm leading-6 text-muted-foreground">
          {planDescription(plan, t)}
        </p>
        <ul className="space-y-3 text-sm">
          {benefits.map((benefit) => (
            <li className="flex items-start gap-2" key={benefit}>
              <CheckIcon
                aria-hidden="true"
                className="mt-0.5 size-4 shrink-0 text-primary"
              />
              <span>{benefit}</span>
            </li>
          ))}
        </ul>
      </CardContent>
      <CardFooter>
        <Button
          className="w-full"
          disabled={
            plan.is_current ||
            simulatedPlanLocked ||
            !detailsComplete ||
            (!hasSubscription && !plan.checkout_available) ||
            !canManage ||
            busy
          }
          onClick={onChoose}
          size="lg"
          variant={highlighted ? "default" : "outline"}
        >
          {pending ? (
            <LoaderCircleIcon aria-hidden="true" className="animate-spin" />
          ) : null}
          {plan.is_current
            ? t("current")
            : !canManage
              ? t(
                  paymentMode === "simulated"
                    ? "simulatedOwnerOnly"
                    : "ownerOnly",
                )
              : !detailsComplete
                ? t("completeDetailsFirst")
                : simulatedPlanLocked
                  ? t("simulatedPlanLocked")
                  : hasSubscription
                    ? t("managePlan")
                    : plan.checkout_available
                      ? t(
                          paymentMode === "simulated"
                            ? "simulatePlan"
                            : "choosePlan",
                        )
                      : t(
                          paymentMode === "simulated"
                            ? "simulationUnavailable"
                            : "checkoutUnavailable",
                        )}
        </Button>
      </CardFooter>
    </Card>
  );
}

function StatusValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-muted/50 p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 font-semibold">{value}</p>
    </div>
  );
}

type Translator = ReturnType<typeof useTranslations<"CustomerBilling">>;

function planBenefits(plan: CustomerPlan, t: Translator, locale: string) {
  const items = [
    t("sitesLimit", { count: plan.quotas["sites.max"] ?? 0 }),
    t("locationsLimit", { count: plan.quotas["locations.max"] ?? 0 }),
    t("appointmentsLimit", {
      count: new Intl.NumberFormat(locale).format(
        plan.quotas["appointments.monthly"] ?? 0,
      ),
    }),
  ];
  if (plan.features.includes("custom_domain.enabled"))
    items.push(t("customDomain"));
  else items.push(t("platformDomain"));
  return items;
}

function planLabel(key: string | null | undefined, t: Translator) {
  const labels: Record<string, string> = {
    profile: t("planProfile"),
    starter: t("planWebsite"),
    pro: t("planPro"),
  };
  return key ? (labels[key] ?? key) : "—";
}

function planDescription(plan: CustomerPlan, t: Translator) {
  const descriptions: Record<string, string> = {
    profile: t("planProfileDescription"),
    starter: t("planWebsiteDescription"),
    pro: t("planProDescription"),
  };
  return descriptions[plan.key] ?? plan.description;
}

function stateLabel(state: string, t: Translator, isSimulated = false) {
  if (isSimulated && state === "grace_period")
    return t("states.simulated_attention");
  const known = new Set([
    "active",
    "canceled",
    "grace_period",
    "read_only",
    "suspended",
    "trialing",
    "unconfigured",
  ]);
  return known.has(state) ? t(`states.${state}`) : state;
}

function accessModeLabel(
  mode: string | null,
  t: Translator,
  isSimulated = false,
) {
  if (mode === "read_only") return t("accessModes.read_only");
  if (mode === "blocked")
    return t(
      isSimulated ? "accessModes.blockedSimulated" : "accessModes.blocked",
    );
  return t("accessModes.unknown");
}

function formatPrice(amount: number, currency: string, locale: string) {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount / 100);
}

function formatDate(value: string | null | undefined, locale: string) {
  return value
    ? new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(
        new Date(value),
      )
    : "—";
}

function errorMessage(
  error: unknown,
  t: Translator,
  paymentMode?: CustomerBillingOverview["payment_mode"],
) {
  if (!(error instanceof ApiProblemError)) return t("loadError");
  const isSimulated = paymentMode === "simulated";
  const known: Record<string, string> = {
    active_subscription_exists: t(
      isSimulated
        ? "simulatedActiveSubscriptionExists"
        : "activeSubscriptionExists",
    ),
    billing_customer_required: t(
      isSimulated ? "simulatedCustomerRequired" : "customerRequired",
    ),
    billing_plan_unavailable: t(
      isSimulated ? "simulationUnavailable" : "planUnavailable",
    ),
    billing_provider_unavailable: t(
      isSimulated ? "simulationUnavailable" : "providerUnavailable",
    ),
    completed_checkout_required: t(
      isSimulated ? "simulatedCheckoutPending" : "checkoutPending",
    ),
    organization_permission_denied: t("noAccess"),
    trial_activation_provider_unavailable: t(
      isSimulated ? "simulationUnavailable" : "providerUnavailable",
    ),
  };
  return known[error.problem.code] ?? t("loadError");
}

function isProblemCode(error: unknown, code: string) {
  return error instanceof ApiProblemError && error.problem.code === code;
}

function wait(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}
