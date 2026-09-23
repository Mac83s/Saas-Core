import { Building2Icon, LockIcon } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { SettingsNotice } from "#components/panel/settings-notice";
import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { HistoryPanel } from "../../../../../modules/core/organizations";

export default async function HistorySettingsPage() {
  const [t, history, organization] = await Promise.all([
    getTranslations("Settings"),
    getTranslations("History"),
    getServerCurrentOrganization(),
  ]);
  return (
    <main className="mx-auto w-full max-w-7xl space-y-7 px-4 py-8 sm:px-6 lg:py-10">
      <header className="space-y-2">
        <p className="text-sm font-medium text-primary">{t("eyebrow")}</p>
        <h1 className="text-3xl font-semibold tracking-tight">
          {history("title")}
        </h1>
        <p className="max-w-2xl text-muted-foreground">
          {history("description")}
        </p>
      </header>
      {!organization ? (
        <SettingsNotice icon={Building2Icon} title={t("noCompanyTitle")}>
          {t("noCompany")}
        </SettingsNotice>
      ) : allows(panelAccess(organization), {
          permission: "organization.settings.manage",
        }) ? (
        <HistoryPanel />
      ) : (
        <SettingsNotice icon={LockIcon} title={t("noAccessTitle")}>
          {t("noAccess")}
        </SettingsNotice>
      )}
    </main>
  );
}
