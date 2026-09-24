import { getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
import { IntegrationsPanel } from "../../../../modules/shared/notifications";

export default async function IntegrationsPage() {
  const [t, settings] = await Promise.all([
    getTranslations("Integrations"),
    getTranslations("Settings"),
  ]);
  return (
    <PanelPage
      description={t("description")}
      eyebrow={settings("eyebrow")}
      title={t("title")}
    >
      <IntegrationsPanel />
    </PanelPage>
  );
}
