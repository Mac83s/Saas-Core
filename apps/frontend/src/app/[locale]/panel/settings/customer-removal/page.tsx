import { notFound } from "next/navigation";
import { Building2Icon, LockIcon } from "lucide-react";

import { PanelPage } from "#components/panel/panel-page";
import { SettingsNotice } from "#components/panel/settings-notice";
import { allows, panelAccess, profileOffers } from "#lib/panel-navigation";
import { getPanelTranslations } from "#lib/panel-messages";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { CustomerRemovalPanel } from "../../../../../modules/shared/customers";

/**
 * Removing one customer's data on request — for a customer with an order or
 * without one. Offered where the profile offers customers' removal after a
 * time (`features.customerRetention`): in a product whose visit hangs on
 * another record of the same person the customer would stay named there
 * (docs/architecture/privacy-retention.md).
 */
export default async function CustomerRemovalPage() {
  if (!profileOffers("customerRetention")) notFound();
  const [t, removal, organization] = await Promise.all([
    getPanelTranslations("Settings"),
    getPanelTranslations("CustomerRemoval"),
    getServerCurrentOrganization(),
  ]);
  const access = organization ? panelAccess(organization) : undefined;
  if (
    access &&
    allows(access, {
      module: "shared.booking",
      permission: "booking.appointment.manage",
    })
  ) {
    return <CustomerRemovalPanel />;
  }
  return (
    <PanelPage
      description={removal("pageDescription")}
      title={removal("pageTitle")}
    >
      {!organization ? (
        <SettingsNotice icon={Building2Icon} title={t("noCompanyTitle")}>
          {t("noCompany")}
        </SettingsNotice>
      ) : (
        <SettingsNotice icon={LockIcon} title={t("noAccessTitle")}>
          {removal("noAccess")}
        </SettingsNotice>
      )}
    </PanelPage>
  );
}
