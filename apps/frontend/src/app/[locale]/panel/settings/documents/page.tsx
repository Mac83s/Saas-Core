import { Building2Icon, LockIcon } from "lucide-react";

import { PanelPage } from "#components/panel/panel-page";
import { SettingsNotice } from "#components/panel/settings-notice";
import { allows, panelAccess } from "#lib/panel-navigation";
import { getPanelTranslations } from "#lib/panel-messages";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { CustomerDocumentsPanel } from "../../../../../modules/shared/customers";

export default async function CustomerDocumentsPage() {
  const [t, documents, organization] = await Promise.all([
    getPanelTranslations("Settings"),
    getPanelTranslations("CustomerDocuments"),
    getServerCurrentOrganization(),
  ]);
  const access = organization ? panelAccess(organization) : undefined;
  if (
    access &&
    allows(access, { module: "shared.customers", permission: "customers.read" })
  ) {
    return <CustomerDocumentsPanel />;
  }
  return (
    <PanelPage
      description={documents("description")}
      title={documents("title")}
    >
      {!organization ? (
        <SettingsNotice icon={Building2Icon} title={t("noCompanyTitle")}>
          {t("noCompany")}
        </SettingsNotice>
      ) : (
        <SettingsNotice icon={LockIcon} title={t("noAccessTitle")}>
          {documents("noAccess")}
        </SettingsNotice>
      )}
    </PanelPage>
  );
}
