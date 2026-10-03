import { notFound } from "next/navigation";
import { getPanelTranslations } from "#lib/panel-messages";

import { PanelPage } from "#components/panel/panel-page";
import { getServerUser } from "#lib/server-auth";
import { PlatformSettings } from "../../../../modules/core/organizations";

/**
 * „Platforma” (platform settings, phase 2; S-T5): the platform's own values,
 * for its operators only — the API refuses everyone else regardless.
 */
export default async function PlatformSettingsPage() {
  const [user, t] = await Promise.all([
    getServerUser(),
    getPanelTranslations("PlatformSettings"),
  ]);
  if ((user?.operator_level ?? 0) < 1) notFound();
  return (
    <PanelPage description={t("description")} form title={t("title")}>
      <PlatformSettings />
    </PanelPage>
  );
}
