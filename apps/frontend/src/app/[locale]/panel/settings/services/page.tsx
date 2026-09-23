import { notFound } from "next/navigation";
import { Building2Icon, LockIcon } from "lucide-react";
import { getTranslations } from "next-intl/server";

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
    <main className="mx-auto w-full max-w-7xl space-y-7 px-4 py-8 sm:px-6 lg:py-10">
      <header className="space-y-2">
        <p className="text-sm font-medium text-primary">{t("eyebrow")}</p>
        <h1 className="text-3xl font-semibold tracking-tight">
          {t("servicesTitle")}
        </h1>
        <p className="max-w-2xl text-muted-foreground">
          {t("servicesDescription")}
        </p>
      </header>
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
    </main>
  );
}
