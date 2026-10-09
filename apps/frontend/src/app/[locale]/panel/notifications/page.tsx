import { notFound } from "next/navigation";
import { getPanelTranslations } from "#lib/panel-messages";

import { PanelPage } from "#components/panel/panel-page";
import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { NotificationsPanel } from "../../../../modules/shared/notifications";

/**
 * Wiadomości › Zapytania ze strony. Without the right to them this is where
 * the automatic notifications show instead, so the menu's single page works.
 * Not in a platform workspace: an enquiry comes from a form on a builder
 * page, and no host serves its builder site (ADR-079 pkt 29).
 */
export default async function NotificationsPage() {
  const [t, inquiries, organization] = await Promise.all([
    getPanelTranslations("Notifications"),
    getPanelTranslations("SiteInquiries"),
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
  if (access.publisher || (!canReadSiteInquiries && !canManageNotifications))
    notFound();
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
