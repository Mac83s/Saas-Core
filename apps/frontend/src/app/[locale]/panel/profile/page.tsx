import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { ProfilePanel } from "../../../../modules/shared/profiles";

export default async function ProfilePage() {
  const [organization, t] = await Promise.all([
    getServerCurrentOrganization(),
    getTranslations("Profile"),
  ]);
  const access = panelAccess(organization);
  if (!allows(access, { module: "shared.profiles" })) notFound();
  return (
    <PanelPage description={t("pageDescription")} title={t("pageTitle")}>
      {/* The API decides; this only keeps the panel from leading to a 403. */}
      <ProfilePanel
        canManage={allows(access, { permission: "profiles.manage" })}
      />
    </PanelPage>
  );
}
