import { getPanelTranslations } from "#lib/panel-messages";

import { PanelPage } from "#components/panel/panel-page";
import { NotificationSupportPanel } from "../../../../../modules/shared/notifications";

export default async function NotificationSupportPage() {
  const t = await getPanelTranslations("NotificationSupport");
  return (
    <PanelPage description={t("description")} title={t("title")}>
      <NotificationSupportPanel />
    </PanelPage>
  );
}
