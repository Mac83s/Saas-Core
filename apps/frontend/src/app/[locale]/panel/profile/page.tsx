import { notFound } from "next/navigation";

import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { ProfilePanel } from "../../../../modules/shared/profiles";

export default async function ProfilePage() {
  const access = panelAccess(await getServerCurrentOrganization());
  if (!allows(access, { module: "shared.profiles" })) notFound();
  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6 lg:py-10">
      {/* The API decides; this only keeps the panel from leading to a 403. */}
      <ProfilePanel
        canManage={allows(access, { permission: "profiles.manage" })}
      />
    </main>
  );
}
