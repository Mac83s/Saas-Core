import { Building2Icon } from "lucide-react";
import { notFound } from "next/navigation";

import { PanelPage } from "#components/panel/panel-page";
import { SettingsNotice } from "#components/panel/settings-notice";
import { getPanelTranslations } from "#lib/panel-messages";
import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { AssistantPanel } from "../../../../modules/shared/assistant";

export default async function AssistantPage() {
  const organization = await getServerCurrentOrganization();
  if (!organization) {
    // Signed in, with no company chosen: say so, like the settings pages.
    const [t, settings] = await Promise.all([
      getPanelTranslations("Assistant"),
      getPanelTranslations("Settings"),
    ]);
    return (
      <PanelPage form title={t("title")}>
        <SettingsNotice icon={Building2Icon} title={settings("noCompanyTitle")}>
          {settings("noCompany")}
        </SettingsNotice>
      </PanelPage>
    );
  }
  if (
    !allows(panelAccess(organization), {
      module: "shared.assistant",
      permission: "assistant.use",
    })
  )
    notFound();
  return (
    <AssistantPanel
      canManageBilling={organization.role === "owner"}
      key={organization.id}
    />
  );
}
