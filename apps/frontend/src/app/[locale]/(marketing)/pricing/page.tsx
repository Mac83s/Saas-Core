import type { Metadata } from "next";
import { CheckIcon } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { Link } from "#i18n/navigation";
import { selfSignupTypes, typeText } from "#lib/organization-types";
import { productCopy, productName } from "../../../../marketing/content";
import { formatPrice, getPublicPlans } from "../../../../marketing/plans";
import { marketingMetadata } from "../../../../marketing/seo";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";

type Props = {
  params: Promise<{ locale: string }>;
  searchParams?: Promise<{ type?: string }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  const { pricing } = productCopy(locale);
  return marketingMetadata({
    locale,
    path: "/pricing",
    title: `${pricing.title} — ${productName}`,
    description: pricing.lead,
  });
}

export default async function PricingPage({ params, searchParams }: Props) {
  const { locale } = await params;
  const requested = (await searchParams)?.type;
  const { pricing } = productCopy(locale);
  const t = await getTranslations("Marketing.pricing");
  // A product with several kinds of customer prices each separately (ADR-050).
  const active =
    selfSignupTypes.find((type) => type.key === requested) ??
    selfSignupTypes[0];
  const plans = await getPublicPlans(active?.key);

  return (
    <section className="mx-auto flex w-full max-w-6xl flex-col gap-10 px-5 py-20">
      <div className="flex max-w-2xl flex-col gap-3">
        <h1 className="text-4xl font-semibold tracking-tight">
          {pricing.title}
        </h1>
        <p className="text-lg text-muted-foreground">{pricing.lead}</p>
      </div>

      {selfSignupTypes.length > 1 ? (
        <nav aria-label={t("forWhom")} className="flex flex-wrap gap-2">
          {selfSignupTypes.map((type) => (
            <Link
              aria-current={type.key === active?.key ? "page" : undefined}
              className="rounded-full border px-4 py-2 text-sm aria-[current=page]:border-primary aria-[current=page]:bg-primary aria-[current=page]:text-primary-foreground"
              href={{ pathname: "/pricing", query: { type: type.key } }}
              key={type.key}
            >
              {typeText(type.label, locale)}
            </Link>
          ))}
        </nav>
      ) : null}

      {plans.length === 0 ? (
        <p className="rounded-lg border p-6 text-muted-foreground">
          {t("unavailable")}{" "}
          <Link href="/contact" className="underline">
            {t("askUs")}
          </Link>
        </p>
      ) : (
        <ul className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {plans.map((plan) => (
            <li key={plan.key}>
              <Card className="h-full">
                <CardHeader>
                  <CardTitle>
                    <h2 className="text-xl">{plan.name}</h2>
                  </CardTitle>
                  {plan.description ? (
                    <CardDescription>{plan.description}</CardDescription>
                  ) : null}
                </CardHeader>
                <CardContent className="flex flex-col gap-5">
                  <p>
                    <span className="text-3xl font-semibold">
                      {formatPrice(plan, locale)}
                    </span>{" "}
                    <span className="text-sm text-muted-foreground">
                      {t(
                        plan.billing_interval === "year"
                          ? "perYear"
                          : "perMonth",
                      )}
                    </span>
                  </p>
                  {plan.trial_days > 0 ? (
                    <p className="text-sm text-primary">
                      {t("trial", { days: plan.trial_days })}
                    </p>
                  ) : null}
                  <ul className="flex flex-col gap-2 text-sm">
                    {plan.features
                      .filter((key) => key in pricing.features)
                      .map((key) => (
                        <li key={key} className="flex items-center gap-2">
                          <CheckIcon
                            aria-hidden="true"
                            className="size-4 text-primary"
                          />
                          {pricing.features[key]}
                        </li>
                      ))}
                  </ul>
                </CardContent>
                <CardFooter className="mt-auto">
                  <Button render={<Link href="/register" />} className="w-full">
                    {t("choose")}
                  </Button>
                </CardFooter>
              </Card>
            </li>
          ))}
        </ul>
      )}

      <p className="text-sm text-muted-foreground">{pricing.note}</p>
    </section>
  );
}
