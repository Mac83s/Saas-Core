import { getPanelTranslations } from "#lib/panel-messages";

import { PanelPage } from "#components/panel/panel-page";
import { IntegrationsPanel } from "../../../../modules/shared/notifications";

export default async function IntegrationsPage() {
  const [t, settings] = await Promise.all([
    getPanelTranslations("Integrations"),
    getPanelTranslations("Settings"),
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
