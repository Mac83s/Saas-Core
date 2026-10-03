import { Building2Icon, LockIcon } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
import { SettingsNotice } from "#components/panel/settings-notice";
import { allows, panelAccess } from "#lib/panel-navigation";
import {
  getServerCurrentOrganization,
  getServerOrganizationOptions,
  getServerSettingsSchema,
} from "#lib/server-auth";
import {
  OrganizationSettings,
  SettingsGroupForm,
} from "../../../../../modules/core/organizations";

export default async function CompanySettingsPage() {
  const [t, organization, options, schema] = await Promise.all([
    getTranslations("Settings"),
    getServerCurrentOrganization(),
    getServerOrganizationOptions(),
    getServerSettingsSchema(),
  ]);
  // Until the settings areas (R4): the company's security next to its details.
  const security = schema?.groups.find(
    (group) => group.key === "organization.security",
  );
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
        <div className="max-w-3xl space-y-6">
          <OrganizationSettings options={options} organization={organization} />
          {security ? <SettingsGroupForm group={security} /> : null}
        </div>
      ) : (
        <SettingsNotice icon={LockIcon} title={t("noAccessTitle")}>
          {t("noAccess")}
        </SettingsNotice>
      )}
    </PanelPage>
  );
}
