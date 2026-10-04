import { Building2Icon, LockIcon } from "lucide-react";

import { PanelPage } from "#components/panel/panel-page";
import { SettingsNotice } from "#components/panel/settings-notice";
import { allows, panelAccess } from "#lib/panel-navigation";
import { getPanelTranslations } from "#lib/panel-messages";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { MarketingConsentsPanel } from "../../../../../modules/shared/customers";

export default async function MarketingConsentsPage() {
  const [t, consents, organization] = await Promise.all([
    getPanelTranslations("Settings"),
    getPanelTranslations("MarketingConsents"),
    getServerCurrentOrganization(),
  ]);
  const access = organization ? panelAccess(organization) : undefined;
  if (
    access &&
    allows(access, { module: "shared.customers", permission: "customers.read" })
  ) {
    return (
      <MarketingConsentsPanel
        canManage={allows(access, {
          module: "shared.customers",
          permission: "customers.manage",
        })}
      />
    );
  }
  return (
    <PanelPage description={consents("description")} title={consents("title")}>
      {!organization ? (
        <SettingsNotice icon={Building2Icon} title={t("noCompanyTitle")}>
          {t("noCompany")}
        </SettingsNotice>
      ) : (
        <SettingsNotice icon={LockIcon} title={t("noAccessTitle")}>
          {consents("noAccess")}
        </SettingsNotice>
      )}
    </PanelPage>
  );
}
