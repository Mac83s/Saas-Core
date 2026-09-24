import { getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
import { EntitlementSupportPanel } from "../../../../../modules/shared/billing";

export default async function BillingSupportPage() {
  const t = await getTranslations("BillingSupport");
  return (
    <PanelPage
      description={t("description")}
      eyebrow={t("eyebrow")}
      title={t("title")}
    >
      <EntitlementSupportPanel />
    </PanelPage>
  );
}
