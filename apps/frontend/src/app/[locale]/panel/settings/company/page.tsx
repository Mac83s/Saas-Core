import { Building2Icon, LockIcon } from "lucide-react";
import { getPanelTranslations } from "#lib/panel-messages";

import { PanelPage } from "#components/panel/panel-page";
import { SettingsNotice } from "#components/panel/settings-notice";
import { allows, panelAccess } from "#lib/panel-navigation";
import {
  getServerCurrentOrganization,
  getServerOrganizationOptions,
} from "#lib/server-auth";
import {
  OrganizationSettings,
  SettingsSearch,
} from "../../../../../modules/core/organizations";

export default async function CompanySettingsPage() {
  const [t, organization, options] = await Promise.all([
    getPanelTranslations("Settings"),
    getServerCurrentOrganization(),
    getServerOrganizationOptions(),
  ]);
  return (
    <PanelPage
      actions={organization ? <SettingsSearch /> : undefined}
      description={t("companyDescription")}
      eyebrow={t("eyebrow")}
      form
      title={t("companyTitle")}
    >
      {!organization ? (
        <SettingsNotice icon={Building2Icon} title={t("noCompanyTitle")}>
          {t("noCompany")}
        </SettingsNotice>
      ) : allows(panelAccess(organization), {
          permission: "organization.settings.manage",
        }) ? (
        <OrganizationSettings options={options} organization={organization} />
      ) : (
        <SettingsNotice icon={LockIcon} title={t("noAccessTitle")}>
          {t("noAccess")}
        </SettingsNotice>
      )}
    </PanelPage>
  );
}
