import { notFound } from "next/navigation";
import { Building2Icon, LockIcon } from "lucide-react";
import { getPanelTranslations } from "#lib/panel-messages";

import { PanelPage } from "#components/panel/panel-page";
import { SettingsNotice } from "#components/panel/settings-notice";
import { allows, panelAccess } from "#lib/panel-navigation";
import {
  getServerCurrentOrganization,
  getServerSettingsSchema,
} from "#lib/server-auth";
import {
  SettingsGroupForm,
  SettingsSearch,
} from "../../../../../modules/core/organizations";

/** The company's booking settings: reminders and the online-booking pause (ADR-078). */
export default async function BookingSettingsPage() {
  const [t, organization, schema] = await Promise.all([
    getPanelTranslations("Settings"),
    getServerCurrentOrganization(),
    getServerSettingsSchema(),
  ]);
  const access = panelAccess(organization);
  if (!allows(access, { module: "shared.booking" })) notFound();
  const groups = (schema?.groups ?? []).filter(
    (group) => group.area === "bookings",
  );
  return (
    <PanelPage
      actions={organization ? <SettingsSearch /> : undefined}
      description={t("bookingsDescription")}
      eyebrow={t("eyebrow")}
      form
      title={t("bookingsTitle")}
    >
      {!organization ? (
        <SettingsNotice icon={Building2Icon} title={t("noCompanyTitle")}>
          {t("noCompany")}
        </SettingsNotice>
      ) : allows(access, { permission: "organization.settings.manage" }) ? (
        <div className="space-y-6">
          {groups.map((group) => (
            <SettingsGroupForm group={group} key={group.key} />
          ))}
        </div>
      ) : (
        <SettingsNotice icon={LockIcon} title={t("noAccessTitle")}>
          {t("noAccess")}
        </SettingsNotice>
      )}
    </PanelPage>
  );
}
