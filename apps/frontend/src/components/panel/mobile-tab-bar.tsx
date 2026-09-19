"use client";

import { EllipsisIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { Link, usePathname } from "#i18n/navigation";
import {
  ariaCurrent,
  panelNavigation,
  type PanelAccess,
} from "#lib/panel-navigation";
import { useSidebar } from "@saas-core/ui/components/sidebar";
import { cn } from "@saas-core/ui/lib/utils";

const item =
  "flex min-h-14 flex-1 flex-col items-center justify-center gap-1 text-[0.6875rem] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring";

/**
 * Phone and tablet: daily work under the thumb (design 1a, 390 px). The first
 * three work entries stay here; everything else is behind "More", which opens
 * the full menu.
 */
export function MobileTabBar({ access }: { access: PanelAccess }) {
  const t = useTranslations("DashboardNav");
  const pathname = usePathname();
  const { mobileOpen, setMobileOpen } = useSidebar();
  const tabs = panelNavigation(access).work.slice(0, 3);

  return (
    <nav
      aria-label={t("primaryNavigation")}
      className="fixed inset-x-0 bottom-0 z-30 flex border-t bg-muted/95 px-1.5 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden"
    >
      {tabs.map((tab) => {
        const current = ariaCurrent(pathname, tab);
        const Icon = tab.icon;
        return (
          <Link
            aria-current={current}
            className={cn(
              item,
              current ? "font-semibold text-primary" : "text-muted-foreground",
            )}
            href={tab.href}
            key={tab.href}
          >
            <Icon aria-hidden="true" className="size-5" />
            {t(tab.labelKey)}
          </Link>
        );
      })}
      <button
        aria-controls="customer-dashboard-sidebar"
        aria-expanded={mobileOpen}
        className={cn(item, "text-muted-foreground")}
        onClick={() => setMobileOpen(true)}
        type="button"
      >
        <EllipsisIcon aria-hidden="true" className="size-5" />
        {t("more")}
      </button>
    </nav>
  );
}
