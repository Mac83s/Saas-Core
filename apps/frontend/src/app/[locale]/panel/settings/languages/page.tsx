import { Building2Icon, LockIcon } from "lucide-react";
import { getPanelTranslations } from "#lib/panel-messages";

import { PanelPage } from "#components/panel/panel-page";
import { SettingsNotice } from "#components/panel/settings-notice";
import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import {
  LanguagesPanel,
  SettingsSearch,
} from "../../../../../modules/core/organizations";
import { SearchVisibility } from "../../../../../modules/shared/sites";

export default async function LanguagesSettingsPage() {
  const [t, languages, organization] = await Promise.all([
    getPanelTranslations("Settings"),
    getPanelTranslations("Languages"),
    getServerCurrentOrganization(),
  ]);
  const access = organization ? panelAccess(organization) : undefined;
  if (
    access &&
    allows(access, { permission: "organization.settings.manage" })
  ) {
    return (
      <LanguagesPanel>
        {/* The sites' own section, for whoever may see the sites (TL19). */}
        {allows(access, {
          module: "shared.sites",
          permission: "site.content.edit",
        }) ? (
          <SearchVisibility />
        ) : null}
      </LanguagesPanel>
    );
  }
  return (
    <PanelPage
      actions={organization ? <SettingsSearch /> : undefined}
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
