import { getTranslations } from "next-intl/server";

import { EntitlementSupportPanel } from "../../../../../modules/shared/billing";

export default async function BillingSupportPage() {
  const t = await getTranslations("BillingSupport");
  return (
    <main className="mx-auto w-full max-w-6xl space-y-8 px-5 py-10">
      <section className="space-y-2">
        <p className="text-sm font-medium text-primary">{t("eyebrow")}</p>
        <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="max-w-3xl text-muted-foreground">{t("description")}</p>
      </section>
      <EntitlementSupportPanel />
    </main>
  );
}
