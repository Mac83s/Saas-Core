import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";

import { AppSidebar } from "#components/panel/app-sidebar";
import { LocaleSwitcher } from "#components/locale-switcher";
import {
  getServerCurrentOrganization,
  getServerCustomerBillingOverview,
  getServerOrganizations,
  getServerUser,
} from "#lib/server-auth";
import { deployment } from "../../../generated/deployment";
import { LogoutButton } from "../../../modules/core/identity";
import { NotificationBell } from "../../../modules/shared/notifications";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@saas-core/ui/components/sidebar";

export default async function PanelLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const [{ locale }, user, organization, organizations, t] = await Promise.all([
    params,
    getServerUser(),
    getServerCurrentOrganization(),
    getServerOrganizations(),
    getTranslations("DashboardNav"),
  ]);
  if (!user) redirect(locale === "pl" ? "/login" : `/${locale}/login`);
  const billing =
    organization?.role === "owner" &&
    new Set<string>(deployment.modules).has("shared.billing")
      ? await getServerCustomerBillingOverview()
      : null;

  return (
    <SidebarProvider>
      <AppSidebar
        canManageBilling={organization?.role === "owner"}
        organizationName={organization?.name}
        organizations={organizations}
        planKey={billing?.subscription?.plan_key}
        planState={billing?.subscription?.state}
        userEmail={user.email}
      />
      <SidebarInset>
        <header className="sticky top-0 z-30 border-b bg-background/90 backdrop-blur-xl">
          <div className="flex h-16 items-center gap-3 px-4 sm:px-6">
            <SidebarTrigger
              aria-controls="customer-dashboard-sidebar"
              aria-label={t("toggleNavigation")}
            />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{t("panel")}</p>
              <p className="hidden truncate text-xs text-muted-foreground sm:block">
                {t("panelDescription")}
              </p>
            </div>
            <div className="ml-auto flex items-center gap-2 sm:gap-3">
              <span className="hidden max-w-56 truncate text-sm text-muted-foreground xl:inline">
                {user.email}
              </span>
              <NotificationBell />
              <LocaleSwitcher />
              <LogoutButton />
            </div>
          </div>
        </header>
        {children}
      </SidebarInset>
    </SidebarProvider>
  );
}
