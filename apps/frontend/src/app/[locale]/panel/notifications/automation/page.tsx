import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { NotificationsPanel } from "../../../../../modules/shared/notifications";

/** Wiadomości › Powiadomienia automatyczne: templates and one's own choices. */
export default async function AutomationPage() {
  const [t, organization] = await Promise.all([
    getTranslations("Notifications"),
    getServerCurrentOrganization(),
  ]);
  if (
    !organization ||
    !allows(panelAccess(organization), {
      module: "shared.notifications",
      permission: "notifications.manage",
    })
  )
    notFound();
  return (
    <PanelPage
      description={t("description")}
      eyebrow={t("eyebrow")}
      title={t("automationTab")}
    >
      <NotificationsPanel
        canManageBilling={organization.role === "owner"}
        section="automation"
      />
    </PanelPage>
  );
}
