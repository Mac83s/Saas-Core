import { Suspense } from "react";
import { getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { CreditsPanel } from "../../../../../modules/shared/billing";

export default async function CreditsSettingsPage() {
  const [t, organization] = await Promise.all([
    getTranslations("Credits"),
    getServerCurrentOrganization(),
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
        <CreditsPanel canManageBilling={organization?.role === "owner"} />
      </Suspense>
    </PanelPage>
  );
}
