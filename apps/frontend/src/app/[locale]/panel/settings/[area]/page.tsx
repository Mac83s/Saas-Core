import { notFound } from "next/navigation";
import { Building2Icon, LockIcon } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { PanelPage } from "#components/panel/panel-page";
import { SettingsNotice } from "#components/panel/settings-notice";
import {
  getServerCurrentOrganization,
  getServerSettingsSchema,
} from "#lib/server-auth";
import {
  SettingsGroupForm,
  SettingsSearch,
} from "../../../../../modules/core/organizations";

/**
 * An area of „Ustawienia” without a page of its own (answer 33a, ADR-078
 * R4): its groups drawn from their declarations, so a module's — or a
 * product's — new settings need no code in the panel.
 */
export default async function SettingsAreaPage({
  params,
}: {
  params: Promise<{ area: string; locale: string }>;
}) {
  const [{ area: key, locale }, t, organization, schema] = await Promise.all([
    params,
    getTranslations("Settings"),
    getServerCurrentOrganization(),
    getServerSettingsSchema(),
  ]);
  const area = schema?.areas.find(
    (item) => item.key === key && item.page === null,
  );
  if (organization && !area) notFound();
  const groups = (schema?.groups ?? []).filter(
    (group) => group.area === key && group.api === null,
  );
  const title = area ? (locale === "en" ? area.title.en : area.title.pl) : "";
  const description = area
    ? locale === "en"
      ? area.description.en
      : area.description.pl
    : "";
  return (
    <PanelPage
      actions={organization ? <SettingsSearch /> : undefined}
      description={description}
      eyebrow={t("eyebrow")}
      form
      title={title || t("eyebrow")}
    >
      {!organization ? (
        <SettingsNotice icon={Building2Icon} title={t("noCompanyTitle")}>
          {t("noCompany")}
        </SettingsNotice>
      ) : groups.some((group) => group.can_change) ? (
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
