import { getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
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
    <PanelPage
      description={t("description")}
      eyebrow={t("eyebrow")}
      title={t("title")}
    >
      <TeamPanel organization={organization} userId={user?.id} />
      {staffAccounts ? <StaffAccountsCard /> : null}
      <OrganizationPanel />
    </PanelPage>
  );
}
