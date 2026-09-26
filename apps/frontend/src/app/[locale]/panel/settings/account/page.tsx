import { getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
import { getServerUser } from "#lib/server-auth";
import {
  PasswordCard,
  ProfileNameForm,
  SessionManager,
  TwoFactorCard,
} from "../../../../../modules/core/identity";
import { OrganizationPanel } from "../../../../../modules/core/organizations";

export default async function AccountSettingsPage() {
  const [t, user] = await Promise.all([
    getTranslations("AccountSettings"),
    getServerUser(),
  ]);
  return (
    <PanelPage
      description={t("description")}
      eyebrow={t("eyebrow")}
      title={t("title")}
    >
      <div className="max-w-3xl space-y-7">
        <ProfileNameForm />
        {user ? <PasswordCard email={user.email} /> : null}
        <TwoFactorCard />
        <SessionManager />
        {/* The companies one works for belong to the account, not a team. */}
        <OrganizationPanel />
      </div>
    </PanelPage>
  );
}
