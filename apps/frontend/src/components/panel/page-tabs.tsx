"use client";

import { Link, usePathname } from "#i18n/navigation";
import { cn } from "@saas-core/ui/lib/utils";

/**
 * The views of one menu entry, as tabs over its content — e.g. Widoczność w
 * Google › Audyt strony | Search Console (answer 47a). Unlike the section's
 * tabs, these stay on every screen: the menu has one entry for them.
 */
export function PageTabs({
  label,
  tabs,
}: {
  label: string;
  tabs: readonly { href: string; label: string }[];
}) {
  const pathname = usePathname();
  return (
    <nav aria-label={label}>
      <ul className="flex gap-1 overflow-x-auto border-b">
        {tabs.map((tab) => (
          <li className="shrink-0" key={tab.href}>
            <Link
              aria-current={pathname === tab.href ? "page" : undefined}
              className={cn(
                "-mb-px flex min-h-11 items-center border-b-2 border-transparent px-3 text-sm font-medium whitespace-nowrap text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
                pathname === tab.href && "border-primary text-foreground",
              )}
              href={tab.href}
            >
              {tab.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
