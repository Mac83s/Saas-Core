import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";

import { AppSidebar } from "#components/panel/app-sidebar";
import { MobileTabBar } from "#components/panel/mobile-tab-bar";
import { PanelHeader } from "#components/panel/panel-header";
import {
  PANEL_WIDTH_COOKIE,
  PanelMain,
  PanelWidthProvider,
} from "#components/panel/panel-width";
import { SectionTabs } from "#components/panel/section-tabs";
import { billingAttention } from "#lib/billing-attention";
import {
  getServerCurrentOrganization,
  getServerCustomerBillingOverview,
  getServerOrganizations,
  getServerUser,
} from "#lib/server-auth";
import { typeRole, typeText } from "#lib/organization-types";
import { panelAccess, type PanelAccess } from "#lib/panel-navigation";
import {
  SidebarInset,
  SidebarProvider,
} from "@saas-core/ui/components/sidebar";

const GLOBAL_ROLES = new Set(["owner", "admin", "manager", "staff", "viewer"]);

export default async function PanelLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const [{ locale }, user, organization, organizations, t, jar] =
    await Promise.all([
      params,
      getServerUser(),
      getServerCurrentOrganization(),
      getServerOrganizations(),
      getTranslations("Organizations"),
      cookies(),
    ]);
  const prefix = locale === "pl" ? "" : `/${locale}`;
  if (!user) redirect(`${prefix}/login`);
  // An account without an organization has nothing to show yet: it starts by
  // saying who it is (ADR-050) instead of landing in an empty panel.
  if (organizations.length === 0) redirect(`${prefix}/onboarding`);

  const access = panelAccess(organization);
  const typeRoleInfo = typeRole(
    organization?.organization_type,
    organization?.role,
  );
  const roleLabel = !organization
    ? ""
    : typeRoleInfo
      ? typeText(typeRoleInfo.label, locale)
      : GLOBAL_ROLES.has(organization.role)
        ? t(organization.role as "owner")
        : t("customRole");
  const attention = await ownerBillingAttention(access);

  return (
    <SidebarProvider>
      <AppSidebar
        access={access}
        attention={attention}
        organizations={organizations}
        roleLabel={roleLabel}
      />
      <SidebarInset className="flex min-h-svh flex-col">
        <PanelWidthProvider
          initialWide={jar.get(PANEL_WIDTH_COOKIE)?.value === "full"}
        >
          <PanelHeader access={access} user={user} />
          <PanelMain>
            {/* On a phone the menu is a drawer away; the section's pages
                stay one tap apart above the content. */}
            <SectionTabs access={access} />
            {children}
          </PanelMain>
        </PanelWidthProvider>
        <MobileTabBar access={access} />
      </SidebarInset>
    </SidebarProvider>
  );
}

/** The subscription card is the owner's business; everyone else skips the call. */
async function ownerBillingAttention(access: PanelAccess) {
  if (!access.isOwner || !access.modules.includes("shared.billing"))
    return null;
  const billing = await getServerCustomerBillingOverview();
  return billing ? billingAttention(billing.subscription, Date.now()) : null;
}
