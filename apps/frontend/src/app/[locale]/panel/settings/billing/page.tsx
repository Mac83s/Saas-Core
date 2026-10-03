import { Suspense } from "react";
import { getLocale } from "next-intl/server";
import { getPanelTranslations } from "#lib/panel-messages";

import { PanelPage } from "#components/panel/panel-page";
import { allows, panelAccess } from "#lib/panel-navigation";
import {
  getServerCurrentOrganization,
  getServerSettingsSchema,
} from "#lib/server-auth";
import { productCopy } from "../../../../../marketing/content";
import { SettingsGroupForm } from "../../../../../modules/core/organizations";
import { CustomerBillingPanel } from "../../../../../modules/shared/billing";

export default async function BillingSettingsPage() {
  const [t, locale, organization, schema] = await Promise.all([
    getPanelTranslations("CustomerBilling"),
    getLocale(),
    getServerCurrentOrganization(),
    getServerSettingsSchema(),
  ]);
  // Who manages billing besides the owner (34a) — shown to the billing roles.
  const access = allows(panelAccess(organization), {
    permission: "organization.billing.manage",
  })
    ? schema?.groups.find((group) => group.key === "billing.access")
    : undefined;
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
      {access ? (
        <div className="mt-6 max-w-3xl">
          <SettingsGroupForm group={access} />
        </div>
      ) : null}
    </PanelPage>
  );
}
