import { Suspense } from "react";
import { getTranslations } from "next-intl/server";

import { CustomerBillingPanel } from "../../../../../modules/shared/billing";

export default async function BillingSettingsPage() {
  const t = await getTranslations("CustomerBilling");
  return (
    <main className="mx-auto w-full max-w-7xl space-y-7 px-4 py-8 sm:px-6 lg:py-10">
      <header className="space-y-2">
        <p className="text-sm font-medium text-primary">{t("eyebrow")}</p>
        <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="max-w-3xl text-muted-foreground">{t("description")}</p>
      </header>
      <Suspense
        fallback={<div className="h-96 animate-pulse rounded-2xl bg-muted" />}
      >
        <CustomerBillingPanel />
      </Suspense>
    </main>
  );
}
