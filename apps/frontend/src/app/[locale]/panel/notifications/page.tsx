import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { NotificationsPanel } from "../../../../modules/shared/notifications";

/**
 * Wiadomości › Zapytania ze strony. Without the right to them this is where
 * the automatic notifications show instead, so the menu's single page works.
 */
export default async function NotificationsPage() {
  const [t, inquiries, organization] = await Promise.all([
    getTranslations("Notifications"),
    getTranslations("SiteInquiries"),
    getServerCurrentOrganization(),
  ]);
  const access = panelAccess(organization);
  const canReadSiteInquiries =
    Boolean(organization) &&
    allows(access, { module: "shared.sites", permission: "site.content.edit" });
  const canManageNotifications =
    Boolean(organization) &&
    allows(access, {
      module: "shared.notifications",
      permission: "notifications.manage",
    });
  if (!canReadSiteInquiries && !canManageNotifications) notFound();
  return (
    <PanelPage
      description={
        canReadSiteInquiries ? inquiries("description") : t("description")
      }
      eyebrow={t("eyebrow")}
      title={canReadSiteInquiries ? inquiries("title") : t("automationTab")}
      titleId="messages-title"
    >
      <NotificationsPanel
        canManageBilling={organization?.role === "owner"}
        canManageNotifications={canManageNotifications}
        canReadSiteInquiries={canReadSiteInquiries}
        titleId="messages-title"
      />
    </PanelPage>
  );
}
