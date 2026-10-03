import { getPanelTranslations } from "#lib/panel-messages";

import { PanelSkeleton } from "#components/panel/panel-page";

/** Between two panel pages: the same placeholder everywhere (ADR-057). */
export default async function PanelLoading() {
  const t = await getPanelTranslations("Common");
  return <PanelSkeleton label={t("loading")} />;
}
