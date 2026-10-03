import { getPanelTranslations } from "#lib/panel-messages";

import { PanelPage } from "#components/panel/panel-page";
import { modulesFor } from "#lib/organization-types";
import { getServerCurrentOrganization, getServerUser } from "#lib/server-auth";
import {
  PasswordCard,
  ProfileNameForm,
  SessionManager,
  TwoFactorCard,
} from "../../../../../modules/core/identity";
import { OrganizationPanel } from "../../../../../modules/core/organizations";
import { NotificationPreferences } from "../../../../../modules/shared/notifications";

export default async function AccountSettingsPage() {
  const [t, user, organization] = await Promise.all([
    getPanelTranslations("AccountSettings"),
    getServerUser(),
    getServerCurrentOrganization(),
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
        {/* One's own messages from this company, for every role (UX-051). */}
        {organization &&
        modulesFor(organization.organization_type).has(
          "shared.notifications",
        ) ? (
          <NotificationPreferences />
        ) : null}
        <SessionManager />
        {/* The companies one works for belong to the account, not a team. */}
        <OrganizationPanel />
      </div>
    </PanelPage>
  );
}
