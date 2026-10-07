import { Suspense } from "react";
import { getPanelTranslations } from "#lib/panel-messages";

import { PanelPage } from "#components/panel/panel-page";
import { companyOnly } from "#lib/company-only";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { CreditsPanel } from "../../../../../modules/shared/billing";

export default async function CreditsSettingsPage() {
  const [t, organization] = await Promise.all([
    getPanelTranslations("Credits"),
    getServerCurrentOrganization(),
  ]);
  // A platform workspace's translations run on the platform's budget, not on
  // credits: there is nothing of its own to show or to buy.
  await companyOnly();
  return (
    <PanelPage
      description={t("description")}
      eyebrow={t("eyebrow")}
      title={t("title")}
    >
      <Suspense
        fallback={<div className="h-96 animate-pulse rounded-xl bg-muted" />}
      >
        <CreditsPanel canManageBilling={organization?.role === "owner"} />
      </Suspense>
    </PanelPage>
  );
}
