import { Building2Icon, LockIcon } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
import { SettingsNotice } from "#components/panel/settings-notice";
import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { HistoryPanel } from "../../../../../modules/core/organizations";

export default async function HistorySettingsPage() {
  const [t, history, organization] = await Promise.all([
    getTranslations("Settings"),
    getTranslations("History"),
    getServerCurrentOrganization(),
  ]);
  return (
    <PanelPage
      description={history("description")}
      eyebrow={t("eyebrow")}
      title={history("title")}
    >
      {!organization ? (
        <SettingsNotice icon={Building2Icon} title={t("noCompanyTitle")}>
          {t("noCompany")}
        </SettingsNotice>
      ) : allows(panelAccess(organization), {
          permission: "organization.settings.manage",
        }) ? (
        <HistoryPanel />
      ) : (
        <SettingsNotice icon={LockIcon} title={t("noAccessTitle")}>
          {t("noAccess")}
        </SettingsNotice>
      )}
    </PanelPage>
  );
}
