import { notFound } from "next/navigation";
import { getPanelTranslations } from "#lib/panel-messages";

import { PanelPage } from "#components/panel/panel-page";
import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { ProfilePanel } from "../../../../modules/shared/profiles";

export default async function ProfilePage() {
  const [organization, t] = await Promise.all([
    getServerCurrentOrganization(),
    getPanelTranslations("Profile"),
  ]);
  const access = panelAccess(organization);
  if (!allows(access, { module: "shared.profiles" })) notFound();
  return (
    <PanelPage description={t("pageDescription")} form title={t("pageTitle")}>
      {/* The API decides; this only keeps the panel from leading to a 403. */}
      <ProfilePanel
        canManage={allows(access, { permission: "profiles.manage" })}
      />
    </PanelPage>
  );
}
