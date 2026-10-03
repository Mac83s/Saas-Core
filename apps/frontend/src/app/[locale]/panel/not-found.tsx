import { getPanelTranslations } from "#lib/panel-messages";

import { PanelPage } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";

/**
 * A panel address that leads nowhere for this account — a page its plan, its
 * product or its role does not include, or one that is gone — under the
 * panel's own menu and in the person's language, instead of the framework's
 * bare English 404.
 */
export default async function PanelNotFound() {
  const t = await getPanelTranslations("Panel");
  return (
    <PanelPage title={t("notFoundTitle")}>
      <div className="max-w-prose space-y-3">
        <p className="text-muted-foreground">{t("notFoundBody")}</p>
        <Link
          className="font-medium text-primary underline-offset-4 hover:underline"
          href="/panel"
        >
          {t("notFoundHome")}
        </Link>
      </div>
    </PanelPage>
  );
}
