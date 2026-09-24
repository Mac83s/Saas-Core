"use client";

import { useTranslations } from "next-intl";

import { Link, usePathname } from "#i18n/navigation";
import {
  currentPage,
  sectionTabs,
  type PanelAccess,
} from "#lib/panel-navigation";
import { cn } from "@saas-core/ui/lib/utils";

/**
 * The pages of the section the page belongs to, e.g. Magazyn › Dokumenty, as
 * tabs above the content — on a phone and a tablet only. A wide screen has
 * them unfolded in the menu (ADR-057).
 */
export function SectionTabs({ access }: { access: PanelAccess }) {
  const t = useTranslations("DashboardNav");
  const pathname = usePathname();
  const tabs = sectionTabs(pathname, access);
  if (!tabs) return null;
  const current = currentPage(pathname, tabs);
  return (
    <nav aria-label={t("sections")} className="-mt-2 mb-6 lg:hidden">
      <ul className="flex gap-1 overflow-x-auto border-b">
        {tabs.map((tab) => {
          const active = tab.href === current;
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
