import { Building2Icon, LockIcon } from "lucide-react";
import { getLocale, getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
import { SettingsNotice } from "#components/panel/settings-notice";
import { allows, panelAccess } from "#lib/panel-navigation";
import { Link } from "#i18n/navigation";
import {
  getServerCurrentOrganization,
  getServerSettingsSchema,
} from "#lib/server-auth";
import {
  HistoryPanel,
  SettingsSearch,
} from "../../../../../modules/core/organizations";

export default async function HistorySettingsPage({
  searchParams,
}: {
  searchParams: Promise<{ group?: string }>;
}) {
  const [{ group }, t, history, organization, locale] = await Promise.all([
    searchParams,
    getTranslations("Settings"),
    getTranslations("History"),
    getServerCurrentOrganization(),
    getLocale(),
  ]);
  // One settings group's changes, from the link under its form (R4).
  const shown = group
    ? (await getServerSettingsSchema())?.groups.find(
        (item) => item.key === group,
      )
    : undefined;
  return (
    <PanelPage
      actions={
        organization ? (
          <>
            {shown ? (
              <Link
                className="text-sm underline-offset-4 hover:underline"
                href="/panel/settings/history"
              >
                {history("allChanges")}
              </Link>
            ) : null}
            <SettingsSearch />
          </>
        ) : undefined
      }
      description={
        shown
          ? history("groupDescription", {
              group: locale === "en" ? shown.title.en : shown.title.pl,
            })
          : history("description")
      }
      eyebrow={t("eyebrow")}
      title={history("title")}
    >
      {!organization ? (
        <SettingsNotice icon={Building2Icon} title={t("noCompanyTitle")}>
          {t("noCompany")}
        </SettingsNotice>
      ) : allows(panelAccess(organization), {
          permission: "organization.settings.manage",
        }) ? (
        <HistoryPanel group={shown?.key} />
      ) : (
        <SettingsNotice icon={LockIcon} title={t("noAccessTitle")}>
          {t("noAccess")}
        </SettingsNotice>
      )}
    </PanelPage>
  );
}
