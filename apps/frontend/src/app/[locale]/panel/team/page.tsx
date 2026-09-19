import { getTranslations } from "next-intl/server";

import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { OrganizationPanel } from "../../../../modules/core/organizations";
import { StaffAccountsCard } from "../../../../modules/shared/booking";

export default async function TeamPage() {
  const [t, organization] = await Promise.all([
    getTranslations("TeamPage"),
    getServerCurrentOrganization(),
  ]);
  // Linking calendar staff to accounts is booking's, and needs its manage right.
  const staffAccounts = allows(panelAccess(organization), {
    module: "shared.booking",
    permission: "booking.appointment.manage",
  });
  return (
    <main className="mx-auto w-full max-w-7xl space-y-7 px-4 py-8 sm:px-6 lg:py-10">
      <header className="space-y-2">
        <p className="text-sm font-medium text-primary">{t("eyebrow")}</p>
        <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="max-w-2xl text-muted-foreground">{t("description")}</p>
      </header>
      <OrganizationPanel />
      {staffAccounts ? <StaffAccountsCard /> : null}
    </main>
  );
}
