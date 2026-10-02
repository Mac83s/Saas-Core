import { Building2Icon, LockIcon } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
import { SettingsNotice } from "#components/panel/settings-notice";
import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { LanguagesPanel } from "../../../../../modules/core/organizations";

export default async function LanguagesSettingsPage() {
  const [t, languages, organization] = await Promise.all([
    getTranslations("Settings"),
    getTranslations("Languages"),
    getServerCurrentOrganization(),
  ]);
  if (
    organization &&
    allows(panelAccess(organization), { permission: "organization.settings.manage" })
  ) {
    return <LanguagesPanel />;
  }
  return (
    <PanelPage
      description={languages("description")}
      eyebrow={t("eyebrow")}
      title={languages("title")}
    >
      {!organization ? (
        <SettingsNotice icon={Building2Icon} title={t("noCompanyTitle")}>
          {t("noCompany")}
        </SettingsNotice>
      ) : (
        <SettingsNotice icon={LockIcon} title={t("noAccessTitle")}>
          {t("noAccess")}
        </SettingsNotice>
      )}
    </PanelPage>
  );
}
