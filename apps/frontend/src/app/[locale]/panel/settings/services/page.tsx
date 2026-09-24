import { notFound } from "next/navigation";
import { Building2Icon, LockIcon } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
import { SettingsNotice } from "#components/panel/settings-notice";
import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { BookingSettings } from "../../../../../modules/shared/booking";

export default async function ServicesSettingsPage() {
  const [t, organization] = await Promise.all([
    getTranslations("Settings"),
    getServerCurrentOrganization(),
  ]);
  const access = panelAccess(organization);
  // Not composed for this deployment or organization type: nothing to set up.
  if (!allows(access, { module: "shared.booking" })) notFound();
  return (
    <PanelPage
      description={t("servicesDescription")}
      eyebrow={t("eyebrow")}
      title={t("servicesTitle")}
    >
      {!organization ? (
        <SettingsNotice icon={Building2Icon} title={t("noCompanyTitle")}>
          {t("noCompany")}
        </SettingsNotice>
      ) : allows(access, { permission: "booking.appointment.manage" }) ? (
        <BookingSettings
          canManageBilling={access.isOwner}
          canUseInventory={allows(access, {
            module: "shared.inventory",
            permission: "inventory.use",
          })}
          organizationType={organization.organization_type}
        />
      ) : (
        <SettingsNotice icon={LockIcon} title={t("noAccessTitle")}>
          {t("noAccess")}
        </SettingsNotice>
      )}
    </PanelPage>
  );
}
