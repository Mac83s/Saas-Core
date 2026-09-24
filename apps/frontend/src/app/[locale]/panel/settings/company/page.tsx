import { Building2Icon, LockIcon } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
import { SettingsNotice } from "#components/panel/settings-notice";
import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { OrganizationSettings } from "../../../../../modules/core/organizations";

export default async function CompanySettingsPage() {
  const [t, organization] = await Promise.all([
    getTranslations("Settings"),
    getServerCurrentOrganization(),
  ]);
  return (
    <PanelPage
      description={t("companyDescription")}
      eyebrow={t("eyebrow")}
      title={t("companyTitle")}
    >
      {!organization ? (
        <SettingsNotice icon={Building2Icon} title={t("noCompanyTitle")}>
          {t("noCompany")}
        </SettingsNotice>
      ) : allows(panelAccess(organization), {
          permission: "organization.settings.manage",
        }) ? (
        <div className="max-w-3xl">
          <OrganizationSettings organization={organization} />
        </div>
      ) : (
        <SettingsNotice icon={LockIcon} title={t("noAccessTitle")}>
          {t("noAccess")}
        </SettingsNotice>
      )}
    </PanelPage>
  );
}
