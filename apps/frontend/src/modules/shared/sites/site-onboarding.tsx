"use client";

import { useEffect, useRef, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  CheckCircle2Icon,
  Globe2Icon,
  LoaderCircleIcon,
  SparklesIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Controller,
  useForm,
  useWatch,
  type SubmitHandler,
} from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  completeSiteOnboarding,
  getSiteOnboarding,
  getSubdomainAvailability,
  saveSiteOnboarding,
  type SiteOnboarding,
  type SiteSummary,
  type SubdomainAvailability,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@saas-core/ui/components/select";

import { mutationKey, type MutationReceipt } from "./idempotency";
import { sitesErrorMessage } from "./problem";

type AddressValues = { subdomain_label: string };
type DetailsValues = { name: string; default_locale: "pl" | "en" };

export function SiteOnboardingWizard({
  onCompleted,
}: {
  onCompleted: (site: SiteSummary) => Promise<void> | void;
}) {
  const t = useTranslations("Sites");
  const [state, setState] = useState<SiteOnboarding>();
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState<string>();
  const [conflict, setConflict] = useState(false);
  const saveReceipt = useRef<MutationReceipt | undefined>(undefined);
  const completeReceipt = useRef<MutationReceipt | undefined>(undefined);

  async function reload() {
    setLoading(true);
    setProblem(undefined);
    setConflict(false);
    try {
      setState(await getSiteOnboarding());
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let active = true;
    getSiteOnboarding()
      .then((loaded) => {
        if (active) setState(loaded);
      })
      .catch((error: unknown) => {
        if (active) setProblem(sitesErrorMessage(error, t));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [t]);

  async function persist(
    step: "address" | "details" | "review",
    values: {
      name: string;
      subdomain_label: string;
      default_locale: "pl" | "en";
    },
  ) {
    if (!state) return;
    setProblem(undefined);
    setConflict(false);
    const input = { version: state.version, step, ...values };
    try {
      const saved = await saveSiteOnboarding(
        input,
        mutationKey(
          saveReceipt,
          `site-onboarding-${state.version}-${step}`,
          input,
        ),
      );
      saveReceipt.current = undefined;
      setState(saved);
    } catch (error) {
      if (
        error instanceof ApiProblemError &&
        error.problem.code === "site_onboarding_version_conflict"
      ) {
        setConflict(true);
      }
      setProblem(sitesErrorMessage(error, t));
    }
  }

  async function complete() {
    if (!state) return;
    setProblem(undefined);
    setConflict(false);
    const payload = { onboarding_id: state.id, version: state.version };
    try {
      const site = await completeSiteOnboarding(
        mutationKey(completeReceipt, "site-onboarding-complete", payload),
      );
      completeReceipt.current = undefined;
      await onCompleted(site);
    } catch (error) {
      if (
        error instanceof ApiProblemError &&
        error.problem.code === "site_onboarding_version_conflict"
      ) {
        setConflict(true);
      }
      setProblem(sitesErrorMessage(error, t));
    }
  }

  if (loading) {
    return (
      <Card aria-busy="true">
        <CardContent className="flex min-h-56 items-center justify-center gap-2 text-sm text-muted-foreground">
          <LoaderCircleIcon aria-hidden="true" className="animate-spin" />
          {t("onboardingLoading")}
        </CardContent>
      </Card>
    );
  }

  if (!state) {
    return (
      <Card>
        <CardContent className="space-y-4 py-8">
          <p className="text-sm text-destructive" role="alert">
            {problem ?? t("problem")}
          </p>
          <Button onClick={() => void reload()} type="button" variant="outline">
            {t("onboardingLoadLatest")}
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <OnboardingProgress step={state.step} />
      {problem ? (
        <div
          className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          role="alert"
        >
          <p>{problem}</p>
          {conflict ? (
            <Button
              className="mt-3"
              onClick={() => void reload()}
              size="sm"
              type="button"
              variant="outline"
            >
              {t("onboardingLoadLatest")}
            </Button>
          ) : null}
        </div>
      ) : null}

      {state.step === "address" ? (
        <AddressStep
          key={`address-${state.version}`}
          onContinue={(label) =>
            persist("details", {
              name: state.name,
              subdomain_label: label,
              default_locale: localeValue(state.default_locale),
            })
          }
          state={state}
        />
      ) : null}
      {state.step === "details" ? (
        <DetailsStep
          key={`details-${state.version}`}
          onBack={(values) =>
            persist("address", {
              ...values,
              subdomain_label: state.subdomain_label,
            })
          }
          onContinue={(values) =>
            persist("review", {
              ...values,
              subdomain_label: state.subdomain_label,
            })
          }
          state={state}
        />
      ) : null}
      {state.step === "review" ? (
        <ReviewStep
          key={`review-${state.version}`}
          onBack={() =>
            persist("details", {
              name: state.name,
              subdomain_label: state.subdomain_label,
              default_locale: localeValue(state.default_locale),
            })
          }
          onComplete={complete}
          state={state}
        />
      ) : null}
    </div>
  );
}

function OnboardingProgress({ step }: { step: string }) {
  const t = useTranslations("Sites");
  const steps = ["address", "details", "review"] as const;
  const currentIndex = Math.max(
    0,
    steps.indexOf(step as (typeof steps)[number]),
  );
  return (
    <ol aria-label={t("onboardingProgress")} className="grid grid-cols-3 gap-2">
      {steps.map((item, index) => (
        <li
          aria-current={index === currentIndex ? "step" : undefined}
          className="flex items-center gap-2 rounded-xl border bg-card px-3 py-2 text-sm"
          key={item}
        >
          <span
            className={
              index <= currentIndex
                ? "flex size-6 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground"
                : "flex size-6 items-center justify-center rounded-full bg-muted text-xs font-semibold text-muted-foreground"
            }
          >
            {index < currentIndex ? (
              <CheckCircle2Icon aria-hidden="true" className="size-4" />
            ) : (
              index + 1
            )}
          </span>
          <span className="hidden sm:inline">
            {t(`onboardingStep_${item}`)}
          </span>
        </li>
      ))}
    </ol>
  );
}

function AddressStep({
  onContinue,
  state,
}: {
  onContinue: (label: string) => Promise<void>;
  state: SiteOnboarding;
}) {
  const t = useTranslations("Sites");
  const [availability, setAvailability] = useState<SubdomainAvailability>();
  const [availabilityProblem, setAvailabilityProblem] = useState<string>();
  const [checking, setChecking] = useState(false);
  const schema = z.object({
    subdomain_label: z.string().trim().min(1, t("required")).max(63),
  });
  const form = useForm<AddressValues>({
    resolver: zodResolver(schema),
    defaultValues: { subdomain_label: state.subdomain_label },
  });
  const watchedLabel = useWatch({
    control: form.control,
    name: "subdomain_label",
  });

  const submit: SubmitHandler<AddressValues> = async ({ subdomain_label }) => {
    setChecking(true);
    setAvailability(undefined);
    setAvailabilityProblem(undefined);
    try {
      const result = await getSubdomainAvailability(subdomain_label);
      setAvailability(result);
      if (result.available) await onContinue(result.normalized_label);
    } catch (error) {
      setAvailabilityProblem(sitesErrorMessage(error, t));
    } finally {
      setChecking(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <span className="flex size-11 items-center justify-center rounded-2xl bg-primary/10 text-primary">
          <Globe2Icon aria-hidden="true" className="size-5" />
        </span>
        <CardTitle className="text-2xl">
          <h2>{t("onboardingAddressTitle")}</h2>
        </CardTitle>
        <CardDescription>{t("onboardingAddressDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-5" onSubmit={form.handleSubmit(submit)}>
          <Field data-invalid={Boolean(form.formState.errors.subdomain_label)}>
            <FieldLabel htmlFor="onboarding-subdomain">
              {t("onboardingAddressLabel")}
            </FieldLabel>
            <div className="flex items-center rounded-lg border bg-background focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50">
              <Input
                aria-invalid={Boolean(form.formState.errors.subdomain_label)}
                className="border-0 shadow-none focus-visible:ring-0"
                id="onboarding-subdomain"
                {...form.register("subdomain_label", {
                  onChange: () => {
                    setAvailability(undefined);
                    setAvailabilityProblem(undefined);
                  },
                })}
              />
              <span className="shrink-0 pr-3 text-sm text-muted-foreground">
                .{state.platform_domain}
              </span>
            </div>
            <FieldDescription>
              {t("onboardingAddressPreview", {
                hostname: `${watchedLabel || t("onboardingAddressPlaceholder")}.${
                  state.platform_domain
                }`,
              })}
            </FieldDescription>
            <FieldError>
              {form.formState.errors.subdomain_label?.message}
            </FieldError>
          </Field>

          {availability && !availability.available ? (
            <div
              className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm"
              role="status"
            >
              <p>{t(`subdomainReason_${availability.reason}`)}</p>
              {availability.suggestion ? (
                <Button
                  className="mt-3"
                  onClick={() => {
                    form.setValue("subdomain_label", availability.suggestion, {
                      shouldDirty: true,
                      shouldValidate: true,
                    });
                    setAvailability(undefined);
                  }}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  {t("onboardingUseSuggestion", {
                    suggestion: availability.suggestion,
                  })}
                </Button>
              ) : null}
            </div>
          ) : null}

          {availabilityProblem ? (
            <p className="text-sm text-destructive" role="alert">
              {availabilityProblem}
            </p>
          ) : null}

          <Button disabled={checking} size="lg" type="submit">
            {checking ? (
              <LoaderCircleIcon aria-hidden="true" className="animate-spin" />
            ) : (
              <ArrowRightIcon aria-hidden="true" />
            )}
            {checking ? t("onboardingChecking") : t("onboardingCheckAddress")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function DetailsStep({
  onBack,
  onContinue,
  state,
}: {
  onBack: (values: DetailsValues) => Promise<void>;
  onContinue: (values: DetailsValues) => Promise<void>;
  state: SiteOnboarding;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const schema = z.object({
    name: z.string().trim().min(2, t("required")).max(160),
    default_locale: z.enum(["pl", "en"]),
  });
  const form = useForm<DetailsValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: state.name,
      default_locale: localeValue(state.default_locale),
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-2xl">
          <h2>{t("onboardingDetailsTitle")}</h2>
        </CardTitle>
        <CardDescription>
          {t("onboardingDetailsDescription", { hostname: state.hostname })}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-5" onSubmit={form.handleSubmit(onContinue)}>
          <FieldGroup>
            <Field data-invalid={Boolean(form.formState.errors.name)}>
              <FieldLabel htmlFor="onboarding-name">
                {t("onboardingBusinessName")}
              </FieldLabel>
              <Input
                aria-invalid={Boolean(form.formState.errors.name)}
                id="onboarding-name"
                {...form.register("name")}
              />
              <FieldDescription>
                {t("onboardingBusinessNameHint")}
              </FieldDescription>
              <FieldError>{form.formState.errors.name?.message}</FieldError>
            </Field>
            <Controller
              control={form.control}
              name="default_locale"
              render={({ field, fieldState }) => (
                <Field data-invalid={fieldState.invalid}>
                  <FieldLabel htmlFor="onboarding-locale">
                    {t("onboardingLanguage")}
                  </FieldLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <SelectTrigger
                      aria-invalid={fieldState.invalid}
                      className="w-full"
                      id="onboarding-locale"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="pl">{common("polish")}</SelectItem>
                      <SelectItem value="en">{common("english")}</SelectItem>
                    </SelectContent>
                  </Select>
                  <FieldDescription>
                    {t("onboardingLanguageHint")}
                  </FieldDescription>
                  <FieldError>{fieldState.error?.message}</FieldError>
                </Field>
              )}
            />
          </FieldGroup>
          <div className="flex flex-wrap gap-3">
            <Button
              disabled={form.formState.isSubmitting}
              onClick={() => void onBack(form.getValues())}
              type="button"
              variant="outline"
            >
              <ArrowLeftIcon aria-hidden="true" />
              {t("onboardingBack")}
            </Button>
            <Button disabled={form.formState.isSubmitting} type="submit">
              <ArrowRightIcon aria-hidden="true" />
              {t("onboardingContinue")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function ReviewStep({
  onBack,
  onComplete,
  state,
}: {
  onBack: () => Promise<void>;
  onComplete: () => Promise<void>;
  state: SiteOnboarding;
}) {
  const t = useTranslations("Sites");
  const [submitting, setSubmitting] = useState(false);

  async function complete() {
    setSubmitting(true);
    try {
      await onComplete();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <span className="flex size-11 items-center justify-center rounded-2xl bg-primary/10 text-primary">
          <SparklesIcon aria-hidden="true" className="size-5" />
        </span>
        <CardTitle className="text-2xl">
          <h2>{t("onboardingReviewTitle")}</h2>
        </CardTitle>
        <CardDescription>{t("onboardingReviewDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <dl className="grid gap-4 rounded-2xl border bg-muted/20 p-5 sm:grid-cols-2">
          <ReviewValue label={t("onboardingBusinessName")} value={state.name} />
          <ReviewValue
            label={t("onboardingFullAddress")}
            value={state.hostname}
          />
          <ReviewValue
            label={t("onboardingLanguage")}
            value={state.default_locale.toUpperCase()}
          />
          <div>
            <dt className="text-sm text-muted-foreground">
              {t("onboardingCustomDomain")}
            </dt>
            <dd className="mt-1">
              <Badge variant="secondary">
                {t("onboardingOptionalUpgrade")}
              </Badge>
            </dd>
          </div>
        </dl>
        <p className="text-sm text-muted-foreground">
          {t("onboardingCustomDomainHint")}
        </p>
        <div className="flex flex-wrap gap-3">
          <Button
            disabled={submitting}
            onClick={() => void onBack()}
            type="button"
            variant="outline"
          >
            <ArrowLeftIcon aria-hidden="true" />
            {t("onboardingBack")}
          </Button>
          <Button
            disabled={submitting}
            onClick={() => void complete()}
            size="lg"
          >
            {submitting ? (
              <LoaderCircleIcon aria-hidden="true" className="animate-spin" />
            ) : (
              <CheckCircle2Icon aria-hidden="true" />
            )}
            {submitting ? t("onboardingCreating") : t("onboardingCreate")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ReviewValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="mt-1 break-words font-medium">{value}</dd>
    </div>
  );
}

function localeValue(value: string): "pl" | "en" {
  return value === "en" ? "en" : "pl";
}
