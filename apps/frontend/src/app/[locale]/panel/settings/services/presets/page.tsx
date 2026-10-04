import { notFound } from "next/navigation";
import { ArrowLeftIcon, Building2Icon, LockIcon } from "lucide-react";
import { getPanelTranslations } from "#lib/panel-messages";

import { PanelPage } from "#components/panel/panel-page";
import { SettingsNotice } from "#components/panel/settings-notice";
import { Link } from "#i18n/navigation";
import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { buttonVariants } from "@saas-core/ui/components/button";
import { OfferPresets } from "../../../../../../modules/shared/booking";

/** „Wzorce ofert” (ADR-072 §10, slice 5g): a sub-page of „Usługi i grafik”. */
export default async function OfferPresetsPage() {
  const [t, settings, organization] = await Promise.all([
    getPanelTranslations("ServicesSetup.presets"),
    getPanelTranslations("Settings"),
    getServerCurrentOrganization(),
  ]);
  const access = panelAccess(organization);
  // Not composed for this deployment or organization type: nothing to start.
  if (!allows(access, { module: "shared.booking" })) notFound();
  return (
    <PanelPage
      actions={
        <Link
          className={buttonVariants({ variant: "outline" })}
          href="/panel/settings/services"
        >
          <ArrowLeftIcon aria-hidden="true" />
          {t("back")}
        </Link>
      }
      description={t("description")}
      eyebrow={settings("eyebrow")}
      title={t("title")}
    >
      {!organization ? (
        <SettingsNotice icon={Building2Icon} title={settings("noCompanyTitle")}>
          {settings("noCompany")}
        </SettingsNotice>
      ) : allows(access, { permission: "booking.appointment.manage" }) ? (
        <OfferPresets
          catalog={allows(access, {
            module: "shared.profiles",
            permission: "profiles.manage",
          })}
          website={allows(access, {
            module: "shared.sites",
            permission: "site.content.edit",
          })}
        />
      ) : (
        <SettingsNotice icon={LockIcon} title={settings("noAccessTitle")}>
          {settings("noAccess")}
        </SettingsNotice>
      )}
    </PanelPage>
  );
}
