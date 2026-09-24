import { Suspense } from "react";
import { getLocale, getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
import { productCopy } from "../../../../../marketing/content";
import { CustomerBillingPanel } from "../../../../../modules/shared/billing";

export default async function BillingSettingsPage() {
  const [t, locale] = await Promise.all([
    getTranslations("CustomerBilling"),
    getLocale(),
  ]);
  return (
    <PanelPage
      description={t("description")}
      eyebrow={t("eyebrow")}
      title={t("title")}
    >
      <Suspense
        fallback={<div className="h-96 animate-pulse rounded-xl bg-muted" />}
      >
        {/* The plans name their features in the words of the pricing page, so
            the offer reads the same before and after signing in. */}
        <CustomerBillingPanel
          featureLabels={productCopy(locale).pricing.features}
        />
      </Suspense>
    </PanelPage>
  );
}
