import { getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
import { NotificationSupportPanel } from "../../../../../modules/shared/notifications";

export default async function NotificationSupportPage() {
  const t = await getTranslations("NotificationSupport");
  return (
    <PanelPage description={t("description")} title={t("title")}>
      <NotificationSupportPanel />
    </PanelPage>
  );
}
