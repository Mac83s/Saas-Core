import { getTranslations } from "next-intl/server";

import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization, getServerUser } from "#lib/server-auth";
import {
  OrganizationPanel,
  TeamPanel,
} from "../../../../modules/core/organizations";
import { StaffAccountsCard } from "../../../../modules/shared/booking";

export default async function TeamPage() {
  const [t, organization, user] = await Promise.all([
    getTranslations("TeamPage"),
    getServerCurrentOrganization(),
    getServerUser(),
  ]);
  // Linking calendar staff to accounts is booking's and needs its manage
  // right — and the team list it links to.
  const access = panelAccess(organization);
  const staffAccounts =
    organization !== null &&
    allows(access, {
      module: "shared.booking",
      permission: "booking.appointment.manage",
    }) &&
    allows(access, { permission: "organization.members.read" });
  return (
    <main className="mx-auto w-full max-w-5xl space-y-7 px-4 py-8 sm:px-6 lg:py-10">
      <header className="space-y-2">
        <p className="text-sm font-medium text-primary">{t("eyebrow")}</p>
        <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="max-w-2xl text-muted-foreground">{t("description")}</p>
      </header>
      <TeamPanel organization={organization} userId={user?.id} />
      {staffAccounts ? <StaffAccountsCard /> : null}
      <OrganizationPanel />
    </main>
  );
}
