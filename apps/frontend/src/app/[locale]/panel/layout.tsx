import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import type { ReactNode } from "react";
import { NextIntlClientProvider } from "next-intl";

import { AppSidebar } from "#components/panel/app-sidebar";
import { PanelDocumentTitle } from "#components/panel/document-title";
import { MobileTabBar } from "#components/panel/mobile-tab-bar";
import { PanelHeader } from "#components/panel/panel-header";
import { PanelMain, PanelWidthProvider } from "#components/panel/panel-width";
import { SectionTabs } from "#components/panel/section-tabs";
import { OrganizationMfaRequired } from "../../../modules/core/organizations/organization-mfa-required";
import { billingAttention } from "#lib/billing-attention";
import {
  getServerBookingOverview,
  getServerCurrentOrganization,
  getServerCustomerBillingOverview,
  getServerOrganizationRequiresMfa,
  getServerOrganizations,
  getServerSettingsSchema,
  getServerUser,
} from "#lib/server-auth";
import { typeRole, typeText } from "#lib/organization-types";
import { getPanelMessages, getPanelTranslations } from "#lib/panel-messages";
import { allows, panelAccess, type PanelAccess } from "#lib/panel-navigation";
import { PANEL_WIDTH_COOKIE } from "#lib/panel-width";
import { isPanelLocale } from "#i18n/routing";
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
  // The proxy sends a guest language to the panel's English (TL17); this is
  // the floor if a request reaches the page another way.
  if (!isPanelLocale((await params).locale)) notFound();
  const [{ locale }, user, organization, organizations, t, jar, words] =
    await Promise.all([
      params,
      getServerUser(),
      getServerCurrentOrganization(),
      getServerOrganizations(),
      getPanelTranslations("Organizations"),
      cookies(),
      getPanelMessages(),
    ]);
  // A company that requires 2FA of this account refuses it until it is on
  // (35a): the panel then shows how to turn it on, whatever page was asked.
  const mfaRequired =
    !organization && organizations.some((item) => item.active)
      ? await getServerOrganizationRequiresMfa()
      : false;
  const prefix = locale === "pl" ? "" : `/${locale}`;
  if (!user) redirect(`${prefix}/login`);
  const operatorLevel = user.operator_level ?? 0;
  // An account without an organization has nothing to show yet: it starts by
  // saying who it is (ADR-050) instead of landing in an empty panel — except
  // a platform operator, whose work is „Platforma” (S-T5).
  if (organizations.length === 0 && operatorLevel < 1)
    redirect(`${prefix}/onboarding`);

  const access =
    organizations.length === 0
      ? { ...panelAccess(null), modules: [], permissions: [], operatorLevel }
      : await withSettingsAreas(
          await withBooking({ ...panelAccess(organization), operatorLevel }),
          locale,
        );
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

  const panel = (
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
          <PanelDocumentTitle company={organization?.name ?? ""} />
          <PanelMain>
            {/* On a phone the menu is a drawer away; the section's pages
                stay one tap apart above the content. */}
            <SectionTabs access={access} />
            {mfaRequired ? (
              <OrganizationMfaRequired
                company={organizations.find((item) => item.active)?.name ?? ""}
              />
            ) : (
              children
            )}
          </PanelMain>
        </PanelWidthProvider>
        <MobileTabBar access={access} />
      </SidebarInset>
    </SidebarProvider>
  );
  // The kind of organization's own words (UX-080), for the client components
  // under it; only a type that has some pays for a second set of messages.
  return words.overridden ? (
    <NextIntlClientProvider messages={words.messages}>
      {panel}
    </NextIntlClientProvider>
  ) : (
    panel
  );
}

/** The subscription card is the owner's business; everyone else skips the call. */
async function ownerBillingAttention(access: PanelAccess) {
  if (!access.isOwner || !access.modules.includes("shared.billing"))
    return null;
  const billing = await getServerCustomerBillingOverview();
  return billing ? billingAttention(billing.subscription, Date.now()) : null;
}

/**
 * The areas of „Ustawienia” the generic page draws (answer 33a): in the menu
 * for whoever may change one of their groups, named as the API names them.
 */
async function withSettingsAreas(
  access: PanelAccess,
  locale: string,
): Promise<PanelAccess> {
  if (!allows(access, { permission: "organization.settings.manage" }))
    return access;
  const schema = await getServerSettingsSchema();
  if (!schema) return access;
  const changeable = new Set(
    schema.groups
      .filter((group) => group.can_change)
      .map((group) => group.area),
  );
  return {
    ...access,
    settingsAreas: schema.areas
      .filter((area) => area.page === null && changeable.has(area.key))
      .map((area) => ({
        key: area.key,
        label: locale === "en" ? area.title.en : area.title.pl,
      })),
  };
}

/**
 * Who takes visits and what waits (ADR-058): the dispatch pages show only
 * where there is somebody to choose between, and the queue carries its count.
 */
async function withBooking(access: PanelAccess): Promise<PanelAccess> {
  if (
    !allows(access, {
      module: "shared.booking",
      permission: "booking.appointment.read",
    })
  )
    return access;
  const overview = await getServerBookingOverview();
  return overview
    ? {
        ...access,
        booking: {
          bookableStaff: overview.bookable_staff,
          teams: overview.teams,
          waiting: overview.waiting,
          requests: overview.requests ?? null,
          stays: overview.stays,
        },
      }
    : access;
}
