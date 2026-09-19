"use client";

import { useTranslations } from "next-intl";

import { Link, usePathname } from "#i18n/navigation";
import { matches, sectionTabs, type PanelAccess } from "#lib/panel-navigation";
import { cn } from "@saas-core/ui/lib/utils";

/** Tabs of the menu entry the page belongs to, e.g. Website › Google visibility. */
export function SectionTabs({ access }: { access: PanelAccess }) {
  const t = useTranslations("DashboardNav");
  const pathname = usePathname();
  const tabs = sectionTabs(pathname, access);
  if (!tabs) return null;
  return (
    <nav
      aria-label={t("sections")}
      className="mx-auto w-full max-w-7xl px-4 pt-6 sm:px-6"
    >
      <ul className="flex gap-1 overflow-x-auto border-b">
        {tabs.map((tab) => {
          const active = matches(pathname, tab.href);
          return (
            <li key={tab.href}>
              <Link
                aria-current={active ? "page" : undefined}
                className={cn(
                  "-mb-px flex min-h-11 items-center border-b-2 border-transparent px-3 text-sm font-medium whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
                  active && "border-primary text-foreground",
                )}
                href={tab.href}
              >
                {t(tab.labelKey)}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
