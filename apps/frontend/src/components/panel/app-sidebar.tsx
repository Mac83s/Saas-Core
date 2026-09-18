"use client";

import {
  CalendarDaysIcon,
  CoinsIcon,
  CreditCardIcon,
  Globe2Icon,
  HomeIcon,
  MessageSquareTextIcon,
  PlugZapIcon,
  SettingsIcon,
  SearchCheckIcon,
  UsersIcon,
  WandSparklesIcon,
  XIcon,
  type LucideIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { Link, usePathname } from "#i18n/navigation";
import type { OrganizationSummary } from "@saas-core/api-client";
import { deployment } from "../../generated/deployment";
import { product } from "../../product";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  useSidebar,
} from "@saas-core/ui/components/sidebar";
import { Button } from "@saas-core/ui/components/button";
import { cn } from "@saas-core/ui/lib/utils";
import { OrganizationSwitcher } from "./organization-switcher";

type NavigationItem = {
  href: string;
  icon: LucideIcon;
  label: string;
  module?: string;
  ownerOnly?: boolean;
};

export function AppSidebar({
  userEmail,
  organizationName,
  organizations,
  canManageBilling,
  planKey,
  planState,
}: {
  userEmail: string;
  organizationName?: string;
  organizations: OrganizationSummary[];
  canManageBilling: boolean;
  planKey?: string | null;
  planState?: string | null;
}) {
  const t = useTranslations("DashboardNav");
  const billing = useTranslations("CustomerBilling");
  const pathname = usePathname();
  const { closeMobile } = useSidebar();
  const modules = new Set<string>(deployment.modules);
  const navigation: NavigationItem[] = [
    { href: "/panel", icon: HomeIcon, label: t("start") },
    {
      href: "/panel/calendar",
      icon: CalendarDaysIcon,
      label: t("calendar"),
      module: "shared.booking",
    },
    {
      href: "/panel/sites",
      icon: Globe2Icon,
      label: t("website"),
      module: "shared.sites",
    },
    {
      href: "/panel/seo",
      icon: SearchCheckIcon,
      label: t("seo"),
      module: "shared.seo",
    },
    {
      href: "/panel/notifications",
      icon: MessageSquareTextIcon,
      label: t("messages"),
      module: "shared.notifications",
    },
    {
      href: "/panel/integrations",
      icon: PlugZapIcon,
      label: t("integrations"),
      module: "shared.notifications",
    },
    ...(product.navigation ?? []).map(({ labelKey, ...item }) => ({
      ...item,
      label: t(labelKey),
    })),
    { href: "/panel/team", icon: UsersIcon, label: t("team") },
    {
      href: "/panel/settings/billing",
      icon: CreditCardIcon,
      label: t("billing"),
      module: "shared.billing",
      ownerOnly: true,
    },
    {
      // No ownerOnly: everybody whose work spends credits should see how many
      // are left; buying stays with the owner, which the panel itself enforces.
      href: "/panel/settings/credits",
      icon: CoinsIcon,
      label: t("credits"),
      module: "shared.billing",
    },
    {
      href: "/panel/settings/account",
      icon: SettingsIcon,
      label: t("settings"),
    },
  ];
  const visibleNavigation = navigation.filter(
    (item) =>
      (!item.module || modules.has(item.module)) &&
      (!item.ownerOnly || canManageBilling),
  );

  return (
    <Sidebar
      aria-label={t("navigation")}
      id="customer-dashboard-sidebar"
      mobileCloseLabel={t("closeNavigation")}
    >
      <SidebarHeader>
        <div className="flex items-center gap-2 pb-3">
          <Link
            className="flex min-h-10 min-w-0 flex-1 items-center gap-3 rounded-xl px-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            href="/panel"
            onClick={closeMobile}
            aria-label={deployment.product.name}
          >
            <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <WandSparklesIcon aria-hidden="true" className="size-5" />
            </span>
            <span className="min-w-0 group-data-[collapsed=true]/sidebar-wrapper:hidden">
              <span className="block truncate text-sm font-semibold">
                {organizationName ?? deployment.product.name}
              </span>
              <span className="block truncate text-xs text-muted-foreground">
                {t("workspace")}
              </span>
            </span>
          </Link>
          <Button
            aria-label={t("closeNavigation")}
            className="lg:hidden"
            onClick={closeMobile}
            size="icon-sm"
            type="button"
            variant="ghost"
          >
            <XIcon aria-hidden="true" />
          </Button>
        </div>
        <OrganizationSwitcher organizations={organizations} />
      </SidebarHeader>
      <SidebarContent>
        {modules.has("shared.billing") && canManageBilling ? (
          <Link
            className="mb-3 flex min-h-12 items-center gap-3 rounded-xl border border-primary/15 bg-primary/[0.035] px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            href="/panel/settings/billing"
            onClick={closeMobile}
            title={
              planKey
                ? `${planLabel(planKey, billing)} · ${stateLabel(planState, billing)}`
                : billing("noPlan")
            }
          >
            <CreditCardIcon
              aria-hidden="true"
              className="size-5 shrink-0 text-primary"
            />
            <span className="min-w-0 group-data-[collapsed=true]/sidebar-wrapper:hidden">
              <span className="block text-xs text-muted-foreground">
                {billing("currentPlan")}
              </span>
              <span className="block truncate font-medium">
                {planKey
                  ? `${planLabel(planKey, billing)} · ${stateLabel(planState, billing)}`
                  : billing("noPlan")}
              </span>
            </span>
          </Link>
        ) : null}
        <nav aria-label={t("primaryNavigation")}>
          <ul className="space-y-1">
            {visibleNavigation.map((item) => {
              const active = isActivePath(pathname, item.href);
              const Icon = item.icon;
              return (
                <li key={item.href}>
                  <Link
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                      active && "bg-primary/10 text-primary",
                    )}
                    href={item.href}
                    onClick={closeMobile}
                    aria-label={item.label}
                    title={item.label}
                  >
                    <Icon aria-hidden="true" className="size-5 shrink-0" />
                    <span className="group-data-[collapsed=true]/sidebar-wrapper:hidden">
                      {item.label}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </SidebarContent>
      <SidebarFooter>
        <div className="flex items-center gap-3 rounded-xl px-3 py-2">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold uppercase text-muted-foreground">
            {userEmail.slice(0, 2)}
          </span>
          <span className="min-w-0 group-data-[collapsed=true]/sidebar-wrapper:hidden">
            <span className="block text-xs text-muted-foreground">
              {t("signedIn")}
            </span>
            <span className="block truncate text-sm font-medium">
              {userEmail}
            </span>
          </span>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}

type BillingTranslator = ReturnType<typeof useTranslations<"CustomerBilling">>;

function planLabel(key: string, t: BillingTranslator) {
  const labels: Record<string, string> = {
    profile: t("planProfile"),
    starter: t("planWebsite"),
    pro: t("planPro"),
  };
  return labels[key] ?? key;
}

function stateLabel(state: string | null | undefined, t: BillingTranslator) {
  const known = new Set([
    "active",
    "canceled",
    "grace_period",
    "read_only",
    "suspended",
    "trialing",
    "unconfigured",
  ]);
  return state && known.has(state)
    ? t(`states.${state}`)
    : t("states.unconfigured");
}

function isActivePath(pathname: string, href: string) {
  return href === "/panel"
    ? pathname === href
    : pathname === href || pathname.startsWith(`${href}/`);
}
