import { Suspense } from "react";
import { getLocale, getTranslations } from "next-intl/server";

import { productCopy } from "../../../../../marketing/content";
import { CustomerBillingPanel } from "../../../../../modules/shared/billing";

export default async function BillingSettingsPage() {
  const [t, locale] = await Promise.all([
    getTranslations("CustomerBilling"),
    getLocale(),
  ]);
  return (
    <main className="mx-auto w-full max-w-7xl space-y-7 px-4 py-8 sm:px-6 lg:py-10">
      <header className="space-y-2">
        <p className="text-sm font-medium text-primary">{t("eyebrow")}</p>
        <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="max-w-3xl text-muted-foreground">{t("description")}</p>
      </header>
      <Suspense
        fallback={<div className="h-96 animate-pulse rounded-xl bg-muted" />}
      >
        {/* The plans name their features in the words of the pricing page, so
            the offer reads the same before and after signing in. */}
        <CustomerBillingPanel
          featureLabels={productCopy(locale).pricing.features}
        />
      </Suspense>
    </main>
  );
}
