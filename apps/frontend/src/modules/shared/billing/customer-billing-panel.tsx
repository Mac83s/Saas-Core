"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import {
  CalendarClockIcon,
  CheckIcon,
  CircleAlertIcon,
  CreditCardIcon,
  ExternalLinkIcon,
  InfoIcon,
  LoaderCircleIcon,
  LockKeyholeIcon,
  MinusIcon,
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
import { billingAttention } from "#lib/billing-attention";
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
import { BillingDetailsForm } from "./billing-details-form";
import {
  DemoPaymentBanner,
  Fact,
  Notice,
  SectionHeader,
  formatDay,
  formatMoney,
} from "./parts";

/** The plan offered first to an organization without one. */
const RECOMMENDED_PLAN = "starter";

/**
 * Limits compared between plans, in the order an owner weighs them. A key the
 * catalogue does not use is skipped.
 * ponytail: core's quota keys only; a product's own quota needs a label here.
 */
const QUOTAS = [
  "sites.max",
  "team_members.max",
  "locations.max",
  "appointments.monthly",
  "storage.bytes",
  "email.monthly",
  "credits.monthly",
] as const;

export function CustomerBillingPanel({
  featureLabels = {},
}: {
  /** Plan features as a customer reads them — the pricing page's own words. */
  featureLabels?: Record<string, string>;
}) {
  const t = useTranslations("CustomerBilling");
  const searchParams = useSearchParams();
  const checkoutState = searchParams.get("checkout");
  const checkoutSessionId = searchParams.get("session_id");
  // Another screen sends the owner here when its feature is not in the plan.
  const requestedFeature = searchParams.get("feature");
  const checkoutKeys = useRef<Record<string, string>>({});
  const activationResultRef = useRef<HTMLDivElement>(null);
  const [overview, setOverview] = useState<CustomerBillingOverview>();
  // When the overview was read: "days left" is counted from it, not from render.
  const [loadedAt, setLoadedAt] = useState(0);
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
      setLoadedAt(Date.now());
    } catch (error) {
      setProblem(errorMessage(error, t));
      setProblemRetry(retryAfterLoad(error));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    let mounted = true;
    void getCustomerBillingOverview()
      .then((data) => {
        if (!mounted) return;
        setOverview(data);
        setLoadedAt(Date.now());
      })
      .catch((error: unknown) => {
        if (mounted) {
          setProblem(errorMessage(error, t));
          setProblemRetry(retryAfterLoad(error));
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
      (plan.is_current && overview?.has_active_subscription) ||
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

  const isSimulated = overview?.payment_mode === "simulated";
  // A free trial is granted once per organization: after any earlier plan the
  // activation starts a paid one, so the panel does not promise a trial.
  const trialEligible =
    !overview?.subscription || overview.subscription.state === "unconfigured";
  const livePlan = overview?.has_active_subscription
    ? overview.plans.find((plan) => plan.is_current)
    : undefined;
  // Only a feature the pricing page names: the message has to say which.
  const featureLabel = requestedFeature
    ? featureLabels[requestedFeature]
    : undefined;
  const missingFeature =
    requestedFeature &&
    featureLabel &&
    !livePlan?.features.includes(requestedFeature)
      ? { key: requestedFeature, label: featureLabel }
      : undefined;
  // The same question as the plan buttons ask: a canceled plan still has a
  // payload, and reading its presence as "already subscribed" is what
  // silently skipped the activation after a real payment.
  const awaitingActivation =
    checkoutState === "success" &&
    overview !== undefined &&
    !overview.has_active_subscription &&
    !activated;
  // One primary action per screen. Back from the payment form it is the
  // activation; otherwise one plan stands out — the cheapest with the feature
  // asked for, else the usual first choice for an organization without a
  // plan — and for a subscriber it is the payment portal.
  const highlighted = awaitingActivation
    ? undefined
    : missingFeature
      ? overview?.plans.find((plan) =>
          plan.features.includes(missingFeature.key),
        )?.key
      : overview?.has_active_subscription
        ? undefined
        : RECOMMENDED_PLAN;

  return (
    <div className="space-y-8">
      {isSimulated ? <DemoPaymentBanner /> : null}

      {awaitingActivation ? (
        <Card className="ring-2 ring-primary">
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
                  ? trialEligible
                    ? "simulatedCheckoutSuccessDescription"
                    : "simulatedCheckoutSuccessPaidDescription"
                  : trialEligible
                    ? "checkoutSuccessDescription"
                    : "checkoutSuccessPaidDescription",
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
              {t(trialEligible ? "activateTrial" : "activatePlan")}
            </Button>
          </CardFooter>
        </Card>
      ) : null}

      {activated ? (
        <Notice
          aria-live="polite"
          icon={CheckIcon}
          ref={activationResultRef}
          role="status"
          tabIndex={-1}
          title={t(
            overview?.subscription?.state === "trialing"
              ? "trialActivatedTitle"
              : "planActivatedTitle",
          )}
          tone="success"
        >
          {t("trialActivatedDescription")}
        </Notice>
      ) : null}

      {checkoutState === "canceled" && overview ? (
        <Notice
          icon={CircleAlertIcon}
          role="status"
          title={t(
            isSimulated
              ? "simulatedCheckoutCanceledTitle"
              : "checkoutCanceledTitle",
          )}
          tone="warning"
        >
          {t(
            isSimulated
              ? "simulatedCheckoutCanceledDescription"
              : "checkoutCanceledDescription",
          )}
        </Notice>
      ) : null}

      {problem ? (
        <Notice
          action={
            problemRetry ? (
              <Button
                disabled={loading || Boolean(pending)}
                onClick={() =>
                  void (problemRetry === "activation"
                    ? activateTrial()
                    : load())
                }
                type="button"
                variant="outline"
              >
                <RefreshCwIcon
                  aria-hidden="true"
                  className={loading || pending ? "animate-spin" : ""}
                />
                {t(problemRetry === "activation" ? "retryActivation" : "retry")}
              </Button>
            ) : null
          }
          icon={CircleAlertIcon}
          role="alert"
          title={problem}
          tone="destructive"
        />
      ) : null}

      {loading && !overview ? (
        <div aria-busy="true" aria-label={t("loading")} className="space-y-4">
          <div className="h-44 animate-pulse rounded-xl bg-muted" />
          <div className="grid gap-4 lg:grid-cols-3">
            {[0, 1, 2].map((item) => (
              <div
                className="h-96 animate-pulse rounded-xl bg-muted"
                key={item}
              />
            ))}
          </div>
        </div>
      ) : null}

      {overview ? (
        <>
          <CurrentPlan
            emphasizePortal={overview.has_active_subscription && !highlighted}
            now={loadedAt}
            onPortal={() => void openPortal()}
            overview={overview}
            pending={pending}
          />
          <BillingDetailsForm
            canManage={overview.can_manage}
            details={overview.billing_details}
            onSaved={(billing_details) =>
              setOverview({ ...overview, billing_details })
            }
          />
          <section aria-labelledby="plans-heading" className="space-y-4">
            <SectionHeader
              description={t("plansDescription")}
              id="plans-heading"
              title={t("plansTitle")}
            />
            {missingFeature ? (
              <Notice
                icon={LockKeyholeIcon}
                title={t("featureMissingTitle", {
                  feature: missingFeature.label,
                })}
                tone="warning"
              >
                {highlighted ? t("featureMissingBody") : null}
              </Notice>
            ) : null}
            <ul className="grid items-stretch gap-4 lg:grid-cols-3">
              {overview.plans.map((plan) => (
                <li className="flex" key={`${plan.key}:${plan.version}`}>
                  <PlanCard
                    badge={
                      plan.is_current && overview.has_active_subscription
                        ? t("currentPlan")
                        : plan.key !== highlighted
                          ? undefined
                          : missingFeature
                            ? t("includesFeature")
                            : t("recommended")
                    }
                    busy={Boolean(pending)}
                    canManage={overview.can_manage}
                    detailsComplete={
                      overview.billing_details.missing.length === 0
                    }
                    featureLabels={featureLabels}
                    hasSubscription={overview.has_active_subscription}
                    highlighted={plan.key === highlighted}
                    onChoose={() => void choosePlan(plan)}
                    paymentMode={overview.payment_mode}
                    pending={pending === plan.key}
                    plan={plan}
                    plans={overview.plans}
                    showTrial={trialEligible}
                  />
                </li>
              ))}
            </ul>
          </section>
        </>
      ) : null}
    </div>
  );
}

function CurrentPlan({
  overview,
  now,
  pending,
  emphasizePortal,
  onPortal,
}: {
  overview: CustomerBillingOverview;
  now: number;
  pending: string | undefined;
  emphasizePortal: boolean;
  onPortal: () => void;
}) {
  const t = useTranslations("CustomerBilling");
  const locale = useLocale();
  const subscription = overview.subscription;
  const isSimulated = overview.payment_mode === "simulated";
  const plan = overview.plans.find((item) => item.is_current);
  const portal =
    overview.payment_mode === "stripe" &&
    overview.portal_available &&
    overview.can_manage;
  // Scheduled to end: a live plan that will not renew.
  const ending =
    overview.has_active_subscription && subscription?.cancel_at_period_end
      ? (subscription.current_period_end ?? subscription.trial_end)
      : null;
  const attention = billingAttention(subscription, now);
  const day = (value: string) => formatDay(value, locale);
  const payment = (label: string, date: string) => ({
    label,
    value: plan
      ? t("paymentValue", {
          date: day(date),
          amount: formatMoney(plan.unit_amount_minor, plan.currency, locale),
        })
      : day(date),
  });

  const facts: { label: string; value: string }[] = [];
  if (plan && overview.has_active_subscription)
    facts.push({
      label: t("priceLabel"),
      value: `${formatMoney(plan.unit_amount_minor, plan.currency, locale)} ${t(
        plan.billing_interval === "year" ? "perYearNet" : "perMonthNet",
      )}`,
    });
  if (subscription?.state === "trialing" && subscription.trial_end) {
    facts.push({ label: t("trialEnds"), value: day(subscription.trial_end) });
    if (!ending) facts.push(payment(t("firstPayment"), subscription.trial_end));
  } else if (ending) {
    facts.push({ label: t("planEnds"), value: day(ending) });
  } else if (
    subscription?.state === "active" &&
    subscription.current_period_end
  ) {
    facts.push(payment(t("nextPayment"), subscription.current_period_end));
  } else if (
    subscription?.state === "grace_period" &&
    subscription.grace_period_end
  ) {
    facts.push({
      label: t("accessUntil"),
      value: day(subscription.grace_period_end),
    });
  }

  // One message, the most urgent: access, then money, then dates.
  const notice =
    attention?.kind === "limited" ? (
      <Notice icon={LockKeyholeIcon} title={t("limitedTitle")} tone="warning">
        {accessModeLabel(subscription?.access_mode ?? null, t, isSimulated)}
      </Notice>
    ) : attention?.kind === "payment" ? (
      <Notice
        icon={CircleAlertIcon}
        title={t(isSimulated ? "simulatedPaymentTitle" : "paymentFailedTitle")}
        tone="destructive"
      >
        {subscription?.grace_period_end
          ? t(isSimulated ? "simulatedGraceEnds" : "graceEnds", {
              date: day(subscription.grace_period_end),
            })
          : null}
      </Notice>
    ) : ending ? (
      <Notice
        icon={CalendarClockIcon}
        title={t("cancelScheduledTitle", { date: day(ending) })}
        tone="warning"
      >
        {t(portal ? "cancelScheduledPortal" : "cancelScheduledBody")}
      </Notice>
    ) : attention?.kind === "trial" ? (
      <Notice
        icon={InfoIcon}
        title={
          attention.days === null
            ? t("trialNoDate")
            : t("trialDaysLeft", { days: attention.days })
        }
        tone="info"
      >
        {t(isSimulated ? "trialBodySimulated" : "trialBody")}
      </Notice>
    ) : attention?.kind === "canceled" ? (
      <Notice icon={CircleAlertIcon} title={t("canceledTitle")} tone="warning">
        {t("canceledBody")}
      </Notice>
    ) : null;

  return (
    <section aria-labelledby="current-plan-heading">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle className="text-muted-foreground">
                <h2 id="current-plan-heading">{t("currentPlan")}</h2>
              </CardTitle>
              <p className="text-2xl font-semibold tracking-tight">
                {subscription?.plan_key
                  ? planLabel(subscription.plan_key, overview.plans, t)
                  : t("noPlan")}
              </p>
            </div>
            {subscription ? (
              <Badge variant={stateBadge(subscription.state, ending)}>
                {ending
                  ? t("states.cancel_scheduled")
                  : stateLabel(subscription.state, t, isSimulated)}
              </Badge>
            ) : null}
          </div>
          {!subscription?.plan_key ? (
            <CardDescription>{t("noPlanDescription")}</CardDescription>
          ) : null}
        </CardHeader>
        {facts.length > 0 || notice ? (
          <CardContent className="space-y-4">
            {facts.length > 0 ? (
              <dl className="grid gap-3 sm:grid-cols-3">
                {facts.map((fact) => (
                  <Fact key={fact.label} {...fact} />
                ))}
              </dl>
            ) : null}
            {notice}
          </CardContent>
        ) : null}
        {portal ? (
          <CardFooter className="flex-wrap gap-3">
            <Button
              disabled={Boolean(pending)}
              onClick={onPortal}
              variant={emphasizePortal ? "default" : "outline"}
            >
              {pending === "portal" ? (
                <LoaderCircleIcon aria-hidden="true" className="animate-spin" />
              ) : (
                <CreditCardIcon aria-hidden="true" />
              )}
              {t(
                subscription?.state === "grace_period"
                  ? "updatePayment"
                  : "managePayment",
              )}
              <ExternalLinkIcon aria-hidden="true" />
            </Button>
            <p className="min-w-0 flex-1 basis-56 text-sm text-muted-foreground">
              {t("portalHelp")}
            </p>
          </CardFooter>
        ) : null}
      </Card>
    </section>
  );
}

function PlanCard({
  plan,
  plans,
  badge,
  highlighted,
  showTrial,
  featureLabels,
  pending,
  busy,
  canManage,
  detailsComplete,
  hasSubscription,
  paymentMode,
  onChoose,
}: {
  plan: CustomerPlan;
  plans: CustomerPlan[];
  badge: string | undefined;
  highlighted: boolean;
  showTrial: boolean;
  featureLabels: Record<string, string>;
  pending: boolean;
  busy: boolean;
  canManage: boolean;
  detailsComplete: boolean;
  hasSubscription: boolean;
  paymentMode: CustomerBillingOverview["payment_mode"];
  onChoose: () => void;
}) {
  const t = useTranslations("CustomerBilling");
  const locale = useLocale();
  // The snapshot keeps naming the last plan after it ended, and the API sells
  // it again then; only a live plan is the one there is nothing to buy.
  const current = plan.is_current && hasSubscription;
  const simulatedPlanLocked =
    paymentMode === "simulated" && hasSubscription && !current;
  // Every card lists the same rows in the same order, so the plans compare
  // line by line; a limit a plan lacks reads as a dash.
  const quotas = QUOTAS.filter((key) =>
    plans.some((item) => key in item.quotas),
  );
  const features = Object.keys(featureLabels).filter((key) =>
    plans.some((item) => item.features.includes(key)),
  );
  return (
    <Card
      className={cn(
        "w-full",
        highlighted && "ring-2 ring-primary",
        current && "ring-2 ring-foreground/25",
      )}
    >
      <CardHeader className="gap-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <CardTitle className="text-lg font-semibold">
            <h3>{planLabel(plan.key, plans, t)}</h3>
          </CardTitle>
          {badge ? (
            <Badge variant={highlighted ? "default" : "secondary"}>
              {badge}
            </Badge>
          ) : null}
        </div>
        <p>
          <span className="text-3xl font-semibold tracking-tight">
            {formatMoney(plan.unit_amount_minor, plan.currency, locale)}
          </span>
          <span className="text-sm text-muted-foreground">
            {" "}
            {t(plan.billing_interval === "year" ? "perYearNet" : "perMonthNet")}
          </span>
        </p>
        {showTrial && plan.trial_days > 0 ? (
          <p className="text-sm font-medium text-primary">
            {t("trialDays", { count: plan.trial_days })}
          </p>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-5">
        {quotas.length > 0 ? (
          <div className="space-y-2">
            <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              {t("limits")}
            </p>
            <dl className="divide-y divide-border">
              {quotas.map((key) => (
                <div
                  className="flex items-baseline justify-between gap-3 py-2"
                  key={key}
                >
                  <dt className="text-muted-foreground">
                    {t(`quotas.${key.replace(".", "_")}`)}
                  </dt>
                  <dd className="font-medium tabular-nums">
                    {key in plan.quotas
                      ? quotaValue(key, plan.quotas[key]!, locale)
                      : "—"}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        ) : null}
        {features.length > 0 ? (
          <div className="space-y-2">
            <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              {t("features")}
            </p>
            <ul className="space-y-2">
              {features.map((key) => {
                const included = plan.features.includes(key);
                return (
                  <li
                    className={cn(
                      "flex items-start gap-2",
                      !included && "text-muted-foreground",
                    )}
                    key={key}
                  >
                    {included ? (
                      <CheckIcon
                        aria-hidden="true"
                        className="mt-0.5 size-4 shrink-0 text-primary"
                      />
                    ) : (
                      <MinusIcon
                        aria-hidden="true"
                        className="mt-0.5 size-4 shrink-0"
                      />
                    )}
                    <span>
                      {featureLabels[key]}
                      {included ? null : (
                        <span className="sr-only">: {t("notIncluded")}</span>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </CardContent>
      <CardFooter>
        <Button
          className="w-full"
          disabled={
            current ||
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
          {current
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

type Translator = ReturnType<typeof useTranslations<"CustomerBilling">>;

function quotaValue(key: string, value: number, locale: string) {
  if (key === "storage.bytes")
    return new Intl.NumberFormat(locale, {
      style: "unit",
      unit: "gigabyte",
      maximumFractionDigits: 1,
    }).format(value / 1024 ** 3);
  return new Intl.NumberFormat(locale).format(value);
}

/** Core plans have translated names; any other plan keeps its catalogue name. */
function planLabel(key: string, plans: CustomerPlan[], t: Translator) {
  const labels: Record<string, string> = {
    profile: t("planProfile"),
    starter: t("planWebsite"),
    pro: t("planPro"),
  };
  return labels[key] ?? plans.find((plan) => plan.key === key)?.name ?? key;
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

function stateBadge(
  state: string,
  ending: string | null,
): "default" | "destructive" | "outline" {
  if (state === "grace_period" || state === "suspended") return "destructive";
  if (!ending && (state === "active" || state === "trialing")) return "default";
  return "outline";
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

/** Retrying a refusal of permission only repeats it. */
function retryAfterLoad(error: unknown): "load" | undefined {
  return isProblemCode(error, "organization_permission_denied")
    ? undefined
    : "load";
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
